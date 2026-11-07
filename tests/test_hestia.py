"""Hestia targets and premium failure attribution, without executing site PHP."""
import json
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_backend as backend
import catalog
import engine
import hestia
import host
import jobs
import state


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0, 'Disposable Linux Hestia lab only')
class HestiaTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown
    api = backend.BackendTests.api

    def test_preferences_default_themes_on_and_remember_explicit_choices(self):
        state.save(state.ROOT/'settings.json', dict(keep_backups=4))
        self.assertEqual(jobs.settings(), dict(keep_backups=4,options={key:True for key in jobs.OPTIONS}))
        choices={key:key not in ('themes','core','backup_themes') for key in jobs.OPTIONS}
        saved=self.api('save_settings',options=choices,keep_backups=2)
        self.assertEqual(saved['settings'], dict(options=choices,keep_backups=2))
        with patch.object(host,'wp_cli',return_value='/usr/local/bin/wp'):
            self.assertEqual(engine.status()['settings'], saved['settings'])
        for invalid in (dict(choices,themes=1), dict(choices,unknown=True), {}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                self.api('save_settings',options=invalid,keep_backups=2)
        self.assertEqual(jobs.settings(), saved['settings'])

    def test_worker_persists_current_site_position_including_failed_sites(self):
        identity='e'*32
        path=state.ROOT/'jobs'/identity;state.mkdir(path)
        sites=[dict(id='a'*32,domain='first.example.test'),dict(id='b'*32,domain='second.example.test')]
        state.save(path/'request.json',dict(kind='update',sites=sites))
        state.save(path/'status.json',dict(id=identity,kind='update',state='queued',message='Queued',results=[]))
        legacy=engine.decorate_job(dict(id=identity,kind='update',state='running',results=[dict(state='failed')]))
        self.assertEqual((legacy['site_index'],legacy['site_total']),(2,2))
        seen=[]
        def update(site, request, job_path, progress):
            current=state.read(job_path/'status.json')
            seen.append((current['site_index'],current['site_total']))
            progress('Updating UltraCache on '+site['domain'])
            current=state.read(job_path/'status.json')
            self.assertEqual(current['message'],'Updating UltraCache on '+site['domain'])
            self.assertEqual((current['site_index'],current['site_total']),seen[-1])
            return dict(site=site['id'],state='failed' if site==sites[0] else 'complete')
        with patch.object(jobs,'update_site',side_effect=update):jobs.worker(identity)
        self.assertEqual(seen,[(1,2),(2,2)])
        final=state.read(path/'status.json')
        self.assertEqual((final['state'],final['site_index'],final['site_total']),('complete',2,2))
        self.assertIn('1 failed site',final['message'])

    def test_temporary_job_options_do_not_overwrite_saved_preferences(self):
        choices={key:key!='themes' for key in jobs.OPTIONS}
        jobs.save_settings(choices,3)
        site=dict(id='a'*32,owner='customer',domain='example.test')
        state.save(state.ROOT/'inventory.json',dict(sites={site['id']:site}))
        options={key:key=='backup_database' for key in jobs.OPTIONS}
        with patch.object(jobs,'current',return_value=None),patch.object(os,'posix_spawn',return_value=1234):
            job=jobs.start('update',[site['id']],options,keep_backups=3)
        self.assertEqual(jobs.settings(),dict(options=choices,keep_backups=3))
        request_path=jobs.directory(job['id'])/'request.json'
        before=request_path.read_bytes()
        self.api('save_settings',options={key:False for key in jobs.OPTIONS},keep_backups=5)
        self.assertEqual(request_path.read_bytes(),before)

    def test_native_roots_and_suspended_domain(self):
        account = dict(user='customer', homedir='/home/customer', status=False)
        replies = [
            {'example.test': {'SUSPENDED': 'no'}, 'off.test': {'SUSPENDED': 'yes'}},
            {'example.test': {'SUSPENDED': 'no', 'DOCUMENT_ROOT': '/home/customer/custom/public/', 'BACKEND': 'PHP-8_3'}},
        ]
        with patch.object(hestia, 'accounts', return_value=[account]), patch.object(hestia, 'cli', side_effect=replies) as cli:
            domains = hestia.domains()
        self.assertEqual(domains, [dict(user='customer', domain='example.test', path='/home/customer/custom/public', url='http://example.test/', php_version='PHP-8_3', backend='PHP-8_3')])
        self.assertEqual(cli.call_count, 2)

    def test_changed_or_suspended_site_cannot_be_updated(self):
        site = dict(owner='customer', uid=1010, gid=1010, home='/home/customer', domain='example.test', path='/home/customer/web/example.test/public_html')
        with patch.object(host, 'accounts', return_value={}):
            with self.assertRaisesRegex(ValueError, 'suspended'): host.refresh_site(site)
        with patch.object(host, 'accounts', return_value={'customer': site}), patch.object(host, 'native', return_value=[dict(user='customer', domain='example.test', path='/home/customer/new')]):
            with self.assertRaisesRegex(ValueError, 'no longer belongs'): host.refresh_site(site)

    def test_php_runtime_uses_domain_template(self):
        with patch.object(Path, 'resolve', return_value=Path('/usr/bin/php8.3')), patch.object(state, 'trusted') as trusted, patch.object(os, 'access', return_value=True):
            self.assertEqual(hestia.php_runtime('PHP-8_3'), '/usr/bin/php8.3')
            trusted.assert_called_once_with(Path('/usr/bin/php8.3'))
        with self.assertRaisesRegex(ValueError, 'Cannot identify'): hestia.php_runtime('unknown-template')

    def test_root_owned_hestia_home_gets_account_private_backup_directory(self):
        home = self.base / 'hestia-home'; home.mkdir(mode=0o751)
        unix = SimpleNamespace(pw_name='customer', pw_uid=65534, pw_gid=65534, pw_dir=str(home))
        site = dict(owner='customer', home=str(home))
        with patch.object(host.pwd, 'getpwnam', return_value=unix):
            host.prepare_backup_home(site)
            host.prepare_backup_home(site)
            folder = home / '.masswpupdate'
            self.assertEqual((folder.stat().st_uid, folder.stat().st_gid, folder.stat().st_mode & 0o777), (65534,65534,0o700))
            folder.rmdir(); folder.symlink_to(self.base, target_is_directory=True)
            with self.assertRaises(OSError): host.prepare_backup_home(site)

    def test_premium_detection_requires_specific_evidence(self):
        for error in ('License expired', 'Invalid licence', 'Subscription activation required', 'Update package not available.', 'Premium plugin requires a package'):
            with self.subTest(error=error): self.assertTrue(jobs.needs_premium_package(error))
        for error in ('HTTP 403 Forbidden', 'Connection timed out', 'Certificate verification failed', 'Could not download: HTTP 500', 'license server connection timeout'):
            with self.subTest(error=error): self.assertFalse(jobs.needs_premium_package(error))

    def test_root_managed_wp_cli_symlink_is_resolved_and_pinned(self):
        target = self.base / 'official.phar'; target.write_text('<?php'); target.chmod(0o644)
        link = self.base / 'wp'; link.symlink_to(target)
        with patch.object(host, 'WP_CLI_CANDIDATES', (str(link),)):
            self.assertEqual(host.wp_cli(), str(target))
            os.chown(link,65534,65534,follow_symlinks=False)
            with self.assertRaisesRegex(ValueError, 'belong to root'): host.wp_cli()

    def test_cleanup_error_does_not_erase_completed_site_work(self):
        site = dict(id='a'*32, domain='example.test', owner='customer')
        inventory = dict(core='7.0', plugins=[], themes=[], multisite=False)
        with patch.object(host, 'refresh_site'), patch.object(host, 'work', return_value=self.base), \
             patch.object(host, 'inventory', return_value=inventory), patch.object(host, 'cleanup', side_effect=OSError('Cleanup device error')):
            result = jobs.update_site(site, dict(options={key:False for key in jobs.OPTIONS}, packages={}), self.base, lambda message:None)
        self.assertEqual(result['state'], 'complete')
        self.assertIn('Cleanup device error', result['warnings'][0])

    def test_pending_entry_deduplicates_and_matching_upload_fills_it(self):
        plugin = dict(file='example-premium/plugin.php', name='Premium', version='1.0')
        site = dict(id='a' * 32)
        first = catalog.register_pending(plugin, site, 'License expired')
        catalog.register_pending(plugin, site, 'License required')
        self.assertEqual(first['version'], '')
        self.assertEqual(catalog.entries()['example-premium']['detected_sites'], [site['id']])
        with self.assertRaisesRegex(ValueError, 'match'):
            catalog.commit(backend.plugin_zip(self.base / 'wrong.zip', main='other.php'))
        uploaded = catalog.commit(backend.plugin_zip(self.base / 'correct.zip'))
        self.assertFalse(catalog.awaiting_zip(uploaded))
        self.assertEqual(uploaded['version'], '2.0.0')
        self.assertTrue(catalog.package(uploaded).is_file())
        catalog.register_pending(plugin, site, 'License expired')
        self.assertEqual(catalog.entries()['example-premium']['sha256'], uploaded['sha256'])

    def test_pending_status_does_not_compare_empty_version_or_allow_apply(self):
        plugin = dict(file='example-premium/plugin.php', name='Premium', version='1.0')
        site = dict(id='a' * 32, domain='example.test', owner='customer', plugins=[plugin])
        catalog.register_pending(plugin, site, 'License required')
        state.save(state.ROOT / 'inventory.json', dict(sites={site['id']: site}))
        with patch.object(host, 'compare', side_effect=AssertionError('Empty version compared')), patch.object(host, 'wp_cli', return_value='/usr/local/bin/wp'):
            result = engine.status()
        self.assertFalse(result['packages'][0]['sites'][0]['newer'])
        with self.assertRaisesRegex(ValueError, 'Upload the waiting'):
            jobs.start('update', [site['id']], {key: key == 'premium' for key in jobs.OPTIONS}, premium='example-premium')
        self.assertEqual(catalog.remove('example-premium')['removed'], 0)

    def test_per_plugin_failure_creates_only_the_correct_pending_entry(self):
        inventory = dict(plugins=[dict(file='paid/plugin.php', name='Paid', version='1'), dict(file='free/free.php', name='Free', version='1')])
        updates = [dict(name='paid', file='paid/plugin.php'), dict(name='free', file='free/free.php')]
        result = dict(actions=[], skipped=[])
        calls = [json.dumps(updates), RuntimeError('License expired'), 'Success']
        with patch.object(host, 'wp', side_effect=calls):
            jobs.regular_plugin_updates(dict(id='a' * 32, domain='example.test'), self.base, inventory, {}, lambda message: None, result)
        self.assertEqual(result['actions'], ['Free'])
        self.assertEqual(result['pending_premium'], ['Paid'])
        self.assertEqual(list(catalog.entries()), ['paid'])

    def test_network_error_does_not_create_premium_entry(self):
        inventory = dict(plugins=[dict(file='paid/plugin.php', name='Paid', version='1')])
        with patch.object(host, 'wp', side_effect=[json.dumps([dict(name='paid', file='paid/plugin.php')]), RuntimeError('HTTP 403 Forbidden')]):
            with self.assertRaisesRegex(RuntimeError, '403'):
                jobs.regular_plugin_updates(dict(id='a' * 32, domain='example.test'), self.base, inventory, {}, lambda message: None, dict(actions=[], skipped=[]))
        self.assertEqual(catalog.entries(), {})

    def test_running_job_keeps_its_pinned_worker_identity_after_code_update(self):
        identity = 'e' * 32
        path = state.ROOT / 'jobs' / identity; state.mkdir(path)
        script = '/opt/addon.releases/old-generation/src/jobs.py'
        state.save(path / 'status.json', dict(id=identity, state='running', pid=1234, worker_script=script))
        state.save(state.ROOT / 'latest.json', dict(id=identity))
        with patch.object(Path, 'read_bytes', return_value=(script + '\0--worker\0' + identity + '\0').encode()):
            self.assertEqual(jobs.current()['state'], 'running')
        with patch.object(Path, 'read_bytes', return_value=b'/usr/bin/some-other-worker\0'):
            self.assertEqual(jobs.current()['state'], 'failed')


if __name__ == '__main__': unittest.main()
