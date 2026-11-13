"""Native account metadata and strictly unprivileged WordPress processes."""
import hashlib
import base64
import functools
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import selectors
import resource
import signal
import stat
import subprocess
import tempfile
import time

import state
import hestia
import php_cli

SOURCE = Path(__file__).resolve().parent
PANEL_PHP = hestia.ROOT / 'php/bin/php'
ENV = hestia.ENV
WP_CLI_CANDIDATES = ('/usr/local/bin/wp', '/usr/bin/wp', '/usr/local/lib/wp-cli/wp-cli.phar')


def native(kind, owner=None):
    if kind not in ('users', 'domains'): raise ValueError('Invalid native discovery action')
    action = hestia.accounts if kind == 'users' else hestia.domains
    return action() if owner is None else action(owner)


def accounts(owner=None):
    result = {}
    for row in (native('users') if owner is None else native('users', owner)):
        name = row['user']
        if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]*', name): raise ValueError('Invalid native account')
        unix = pwd.getpwnam(name)
        if unix.pw_uid == 0 or name == 'hestiaweb' or unix.pw_dir != row['homedir']:
            raise ValueError('Native account identity mismatch')
        if row['status']: continue
        result[name] = dict(owner=name, uid=unix.pw_uid, gid=unix.pw_gid, home=unix.pw_dir)
    return result


def runtime(version='', owner=None, domain=None):
    return hestia.php_runtime(version, owner, domain)


def wp_cli():
    for candidate in WP_CLI_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            # A root-managed WP-CLI symlink is a normal installation layout.
            # Pin the resolved trusted file; never execute through a mutable link.
            state.trusted(path.parent, True)
            if path.lstat().st_uid != 0: raise ValueError('WP-CLI must belong to root')
            target = path.resolve(strict=True)
            state.trusted(target)
            if target.stat().st_mode & 0o022: raise ValueError('WP-CLI must be writable only by root')
            return str(target)
    raise ValueError('WP-CLI is required. Install its official PHAR at /usr/local/bin/wp, then refresh sites.')


def work(account):
    state.trusted(state.WORK, True)
    destination = state.WORK / secrets.token_hex(16)
    destination.mkdir(mode=0o700)
    os.chown(destination, account['uid'], account['gid'])
    return destination


def cleanup(path):
    # fd-based rmtree does not follow links planted by a compromised account.
    import shutil
    if path.parent != state.WORK or not re.fullmatch('[0-9a-f]{32}', path.name): raise ValueError('Invalid work directory')
    if path.is_symlink() or not shutil.rmtree.avoids_symlink_attacks: raise ValueError('Unsafe work cleanup')
    shutil.rmtree(path)


def account_path():
    # Hestia may link mysqldump into /usr/bin while WP-CLI invokes its real
    # MariaDB name. Include the active native client's root-owned bin directory.
    directories = []
    for name in ('mysqldump', 'mysql', 'mariadb-dump', 'mariadb'):
        for base in ('/usr/local/bin', '/usr/bin'):
            candidate = Path(base) / name
            if candidate.exists():
                target = candidate.resolve(strict=True)
                state.trusted(target); state.trusted(target.parent, True)
                if not os.access(target, os.X_OK): continue
                if str(target.parent) not in directories: directories.append(str(target.parent))
                break
    return ':'.join(directories + ENV['PATH'].split(':'))


def run_as(account, arguments, cwd, timeout=None, output=None, database=False, input_source=None):
    unix = pwd.getpwnam(account['owner'])
    if (unix.pw_uid == 0 or unix.pw_name == 'hestiaweb' or unix.pw_uid != account['uid'] or
            unix.pw_gid != account['gid'] or unix.pw_dir != account['home']):
        raise ValueError('Hosting account changed; refresh sites before updating')
    env = {**ENV, 'PATH': account_path() if database else ENV['PATH'], 'HOME': str(cwd), 'USER': unix.pw_name, 'LOGNAME': unix.pw_name,
           'WP_CLI_CONFIG_PATH': '/dev/null', 'WP_CLI_DISABLE_AUTO_CHECK_UPDATE': '1',
           'WP_CLI_CACHE_DIR': str(cwd / 'cache'), 'WP_CLI_PACKAGES_DIR': str(cwd / 'packages')}
    # Backups use an inherited, already-open root-private output descriptor. Limit
    # that file to available space while reserving 256 MiB for the running host.
    cap = None
    if output is not None:
        available = os.fstatvfs(output.fileno())
        cap = available.f_bavail * available.f_frsize - 256 * 1024 * 1024
        if cap <= 0: raise RuntimeError('Insufficient free space for a backup')
    def limits():
        if cap is not None: resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    with subprocess.Popen([str(a) for a in arguments], cwd=cwd, env=env, stdin=input_source if input_source is not None else subprocess.DEVNULL,
            stdout=output if output is not None else subprocess.PIPE, stderr=subprocess.PIPE,
            user=unix.pw_uid, group=unix.pw_gid, extra_groups=[], umask=0o077,
            start_new_session=True, preexec_fn=limits) as child:
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        deadline = time.monotonic() + timeout if timeout is not None else None
        try:
            with selectors.DefaultSelector() as selector:
                if child.stdout: selector.register(child.stdout, selectors.EVENT_READ, 'stdout')
                selector.register(child.stderr, selectors.EVENT_READ, 'stderr')
                while selector.get_map():
                    remaining = deadline - time.monotonic() if deadline is not None else None
                    if remaining is not None and remaining <= 0: raise RuntimeError('Site command timed out; inspect the site before retrying')
                    for key, unused in selector.select(min(remaining, 1) if remaining is not None else None):
                        block = os.read(key.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(key.fileobj); continue
                        buffers[key.data].extend(block)
                child.wait(timeout=max(0.01, deadline - time.monotonic()) if deadline is not None else None)
        except Exception:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
            raise
        stdout, stderr = bytes(buffers['stdout']), bytes(buffers['stderr'])
        if child.returncode:
            details = b'\n'.join(part for part in (stderr, stdout) if part)
            message = (details or b'Site command failed').decode('utf-8', errors='replace')
            raise RuntimeError('Site command failed: ' + message)
        return (stdout or b'').decode('utf-8', errors='replace')


def account_task(account, operation, cwd, path=None, output=None):
    args = ['/usr/bin/python3', '-I', '-B', SOURCE / 'account_task.py', operation, account['home']]
    if path is not None: args.append(path)
    return run_as(account, args, cwd, output=output)


def wp(site, args, cwd, timeout=None, output=None):
    account_task(site, 'check', cwd, site['path'])
    flags = []
    if args[:2] == ['db', 'export']:
        # WP-CLI intentionally skips client option files. Match PHP's local
        # socket when DB_HOST is localhost; preserve explicit remote/socket hosts.
        socket=database_socket(site,cwd)
        if socket:args=[*args,'--socket='+socket]
        disabled = json.loads(run_as(site, [site['php_bin'], '-r', php_cli.DISABLED_FUNCTIONS], cwd))
        flags = php_cli.database_flags(disabled)
    # This process is already the account UID before PHP or wp-config.php loads.
    return run_as(site, [site['php_bin'], *flags, wp_cli(), '--path=' + site['path'], '--skip-plugins',
        '--skip-themes', '--skip-packages', '--no-color', *args], cwd, timeout, output, database=args[:2] == ['db', 'export'])


def install_premium(site, record, source, cwd):
    # Read the installed header again inside the account's installing WP-CLI
    # process. A stale scan/plan must not turn --force into a downgrade.
    payload = base64.b64encode(json.dumps(dict(file=record['plugin_file'], version=record['version'],
                                               zip=str(source))).encode()).decode()
    code = '''require_once ABSPATH.'wp-admin/includes/plugin.php';
$p=json_decode(base64_decode('PAYLOAD'),true);
$file=WP_PLUGIN_DIR.'/'.$p['file'];
if(!is_file($file)){$r=array('installed'=>false,'reason'=>'not installed');}
else{
 $data=get_plugin_data($file,false,false);$v=$data['Version'];
 if($v===''){WP_CLI::error('The installed plugin version could not be read.');}
 if(version_compare($v,$p['version'],'>=')){$r=array('installed'=>false,'reason'=>'installed version '.$v.' is current or newer');}
 else{WP_CLI::get_runner()->run_command(array('plugin','install',$p['zip']),array('force'=>true));$r=array('installed'=>true);}
}
echo "\\nMWU_PREMIUM_RESULT=".json_encode($r)."\\n";'''.replace('PAYLOAD', payload)
    output = wp(site, ['eval', code], cwd)
    results = re.findall(r'^MWU_PREMIUM_RESULT=(.+)$', output, re.M)
    if not results:
        raise RuntimeError('The premium installer did not return its version decision: ' + output)
    return json.loads(results[-1])


def database_socket(site,cwd):
    connection=json.loads(wp(site,['eval',"echo json_encode(array('host'=>DB_HOST,'socket'=>ini_get('mysqli.default_socket')));"],cwd))
    if not isinstance(connection,dict) or set(connection)!={'host','socket'}:raise ValueError('Cannot determine the WordPress database connection')
    socket=connection['socket'] if connection['host']=='localhost' else ''
    if socket and (not isinstance(socket,str) or not socket.startswith('/') or len(socket)>4096 or any(ord(c)<32 for c in socket)):
        raise ValueError('Invalid local database socket')
    return socket or ''


def database_connection(site, cwd):
    # Only connection identity is returned; database passwords never cross the
    # WordPress process boundary or appear in arguments, manifests or logs.
    code = "echo json_encode(array('name'=>DB_NAME,'host'=>DB_HOST,'port'=>(int)ini_get('mysqli.default_port')));"
    connection = json.loads(wp(site, ['eval', code], cwd))
    if (not isinstance(connection, dict) or set(connection) != {'name', 'host', 'port'} or
            any(not isinstance(connection[key], str) or not connection[key] or
                any(ord(c) < 32 for c in connection[key]) for key in ('name', 'host')) or
            type(connection['port']) is not int):
        raise ValueError('Cannot determine the WordPress database connection')
    return connection


def backup_task(site,operation,scratch,request,output=None):
    if operation not in ('prepare','archive','commit','prune','read','delete_site'):raise ValueError('Invalid account backup operation')
    payload={**request,'path':site['path']}
    database=operation=='archive' and request.get('kind')=='database'
    if database:
        target = hestia.database_target(site['owner'], database_connection(site, scratch))
        if target is not None:
            # Hestia alone invokes its native dump. Pass an already-open private
            # descriptor to the account ZIP writer; no root-written account path.
            state.trusted(state.ROOT / 'backups', True)
            with tempfile.TemporaryFile(dir=state.ROOT / 'backups') as sql:
                hestia.dump_database(site['owner'], target, sql)
                payload['database_source'] = 'hestia'
                raw = run_as(site, ['/usr/bin/python3', '-I', '-B', SOURCE / 'account_backups.py',
                             operation, site['home'], json.dumps(payload)], scratch, output=output, input_source=sql)
            return json.loads(raw) if output is None else None
        payload.update(php=site['php_bin'],wp=wp_cli(),socket=database_socket(site,scratch))
    raw=run_as(site,['/usr/bin/python3','-I','-B',SOURCE/'account_backups.py',operation,site['home'],json.dumps(payload)],
               scratch,output=output,database=database)
    return json.loads(raw) if output is None else None


def private_backup_home(site):
    target=Path(site['home'])/'.masswpupdate'
    for row in native('domains', site['owner']):
        if row['user']!=site['owner']:continue
        document_root=Path(row['path'])
        if not document_root.is_absolute() or '..' in document_root.parts:raise ValueError('Invalid native document root')
        if target.is_relative_to(document_root) or document_root.is_relative_to(target):
            raise ValueError('The private account storage overlaps a Hestia document root')
    prepare_backup_home(site)


def library_location():
    return str(Path(pwd.getpwnam(hestia.name(state.account())).pw_dir) / '.masswpupdate/premium')


def library_task(operation, record, source=None, output=None):
    owner = state.account()
    if owner is None:
        raise ValueError('A personal library requires an account scope')
    account = accounts(owner).get(owner)
    if not account:
        raise ValueError('The hosting account is unavailable or suspended')
    private_backup_home(account)
    scratch = work(account)
    try:
        args = ['/usr/bin/python3', '-I', '-B', SOURCE / 'account_library.py', operation,
                account['home'], json.dumps(record)]
        raw = run_as(account, args, scratch, output=output, input_source=source)
        return json.loads(raw) if output is None else None
    finally:
        cleanup(scratch)


def prepare_backup_home(site):
    # Hestia owns /home/USER as root. Prepare only our private directory;
    # the account process writes every archive and manifest itself.
    unix = pwd.getpwnam(site['owner'])
    if unix.pw_uid == 0 or unix.pw_dir != site['home'] or unix.pw_name == hestia.PANEL_USER:
        raise ValueError('Invalid backup hosting identity')
    home = Path(site['home'])
    state.trusted(home.parent, True)
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        created = False
        try:
            os.mkdir('.masswpupdate', 0o700, dir_fd=fd)
            created = True
        except FileExistsError:
            pass
        backup_fd = os.open('.masswpupdate', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            if created: os.fchown(backup_fd, unix.pw_uid, unix.pw_gid)
            info = os.fstat(backup_fd)
            if info.st_uid != unix.pw_uid or info.st_gid != unix.pw_gid or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('The account backup directory must belong to its account with mode 700')
        finally: os.close(backup_fd)
    finally: os.close(fd)


@functools.lru_cache(maxsize=4096)
def compare(a, b):
    result = subprocess.run([str(PANEL_PHP), '-n', '-r', 'echo version_compare($argv[1],$argv[2]);', '--', str(a), str(b)],
        env=ENV, capture_output=True, text=True, check=True)
    return int(result.stdout)


INVENTORY = '''require_once ABSPATH.'wp-admin/includes/plugin.php';
$p=array();foreach(get_plugins() as $file=>$v){$p[]=array('file'=>$file,'name'=>$v['Name'],'version'=>$v['Version'],'active'=>is_plugin_active($file));}
$t=array();foreach(wp_get_themes() as $slug=>$v){$t[]=array('slug'=>$slug,'version'=>$v->get('Version'));}
echo json_encode(array('core'=>get_bloginfo('version'),'php'=>PHP_VERSION,'plugins'=>$p,'themes'=>$t,'multisite'=>is_multisite(),
'layout_ok'=>WP_CONTENT_DIR===ABSPATH.'wp-content' && WP_PLUGIN_DIR===WP_CONTENT_DIR.'/plugins' && get_theme_root()===WP_CONTENT_DIR.'/themes'));'''


def inventory(site, cwd):
    value = json.loads(wp(site, ['eval', INVENTORY], cwd))
    if not isinstance(value, dict) or set(value) != {'core', 'php', 'plugins', 'themes', 'multisite', 'layout_ok'}:
        raise ValueError('Invalid WordPress inventory response')
    if not isinstance(value['plugins'], list) or not isinstance(value['themes'], list): raise ValueError('Invalid site inventory')
    if value['layout_ok'] is not True: raise ValueError('Custom content, plugin or theme directories are not supported')
    if type(value['multisite']) is not bool: raise ValueError('Invalid WordPress network inventory')
    del value['layout_ok']
    if any(not isinstance(value[k], str) or len(value[k]) > 128 for k in ('core', 'php')):
        raise ValueError('Invalid site runtime version')
    import catalog
    for plugin in value['plugins']:
        if not isinstance(plugin, dict): raise ValueError('Invalid plugin inventory')
        if not isinstance(plugin.get('file'), str) or len(plugin['file'].split('/')) not in (1, 2): raise ValueError('Unsupported plugin layout')
        try:
            for piece in plugin['file'].split('/'): catalog.component(piece)
        except ValueError as error:
            raise ValueError('Invalid plugin file ' + repr(plugin['file']) + ': ' + str(error)) from error
        if not isinstance(plugin.get('version'), str) or len(plugin['version']) > 128: raise ValueError('Invalid installed plugin version')
    for theme in value['themes']:
        if not isinstance(theme, dict) or not isinstance(theme.get('version'), str): raise ValueError('Invalid theme inventory')
        try: catalog.component(theme['slug'])
        except ValueError as error:
            raise ValueError('Invalid theme directory ' + repr(theme['slug']) + ': ' + str(error)) from error
    return value


def discover(progress, owner=None):
    owners = accounts() if owner is None else accounts(owner)
    domains = native('domains') if owner is None else native('domains', owner)
    result, errors = {}, []
    for account in owners.values():
        scratch = work(account)
        try:
            roots = sorted({d['path'] for d in domains if d['user'] == account['owner']})
            paths = json.loads(account_task(account, 'discover', scratch, json.dumps(roots)))
            for path in paths:
                site = {**account, 'path': path, 'id': hashlib.sha256((account['owner'] + '\0' + path).encode()).hexdigest()[:32]}
                matching = [d for d in domains if d['user'] == account['owner'] and
                            (path == d['path'] or path.startswith(d['path'].rstrip('/') + '/'))]
                matching.sort(key=lambda d: -len(d['path']))
                if not matching: continue
                domain = matching[0]
                from urllib.parse import quote
                relative = str(Path(path).relative_to(domain['path']))
                site.update(domain=domain['domain'], url=domain['url'] + (quote(relative, safe='/') + '/' if relative != '.' else ''))
                try:
                    site['php_bin'] = runtime(domain.get('php_version') or '', account['owner'], domain['domain'])
                    progress('Reading ' + site['domain'])
                    site.update(inventory(site, scratch))
                except Exception as error:
                    site['error'] = str(error)
                result[site['id']] = site
        except Exception as error:
            errors.append(dict(owner=account['owner'], error=str(error)))
        finally:
            try: cleanup(scratch)
            except Exception as error:
                errors.append(dict(owner=account['owner'], error='Temporary working files could not be removed: ' + str(error)))
    return dict(sites=result, errors=errors)


def refresh_site(site):
    """Recheck current native ownership, suspension, root and runtime per site."""
    account = accounts(site['owner']).get(site['owner'])
    if not account or any(site[key] != account[key] for key in ('uid', 'gid', 'home')):
        raise ValueError('The Hestia account changed or is suspended; refresh sites')
    matches = [d for d in native('domains', site['owner']) if d['user'] == site['owner']
               and d['domain'] == site['domain']
               and (site['path'] == d['path'] or site['path'].startswith(d['path'].rstrip('/') + '/'))]
    if len(matches) != 1:
        raise ValueError('The site no longer belongs to its active Hestia domain; refresh sites')
    domain = matches[0]
    site['php_bin'] = runtime(domain['php_version'], site['owner'], site['domain'])
    return site
