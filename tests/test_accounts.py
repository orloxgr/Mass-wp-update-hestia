"""Cross-account API isolation and personal-library regression coverage."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_backend as backend
import catalog
import engine
import host
import jobs
import state
import hestia


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0, 'Disposable Linux lab only')
class AccountTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown

    def api(self, action, actor='nobody', **values):
        return engine.dispatch(dict(actor=actor, admin=False, action=action, **values))

    def sites(self):
        own = dict(id='a'*32, owner='nobody', domain='own.example.test', path='/nonexistent/site', plugins=[])
        other = dict(id='b'*32, owner='daemon', domain='other.example.test', path='/usr/sbin/site', plugins=[])
        state.save(state.ROOT/'inventory.json', dict(sites={own['id']:own, other['id']:other},
                   errors=[dict(owner='daemon', error='other account secret')], scanned_at=123))
        return own, other

    def job(self, identity, scope, site, state_value='complete'):
        path = state.ROOT/'jobs'/identity; state.mkdir(path)
        state.save(path/'request.json', dict(scope=scope, kind='update', sites=[site]))
        value = dict(id=identity, scope=scope, kind='update', state=state_value, created=100,
                     message='Working on '+site['domain'], results=[dict(site=site['id'], owner=site['owner'])])
        state.save(path/'status.json', value)
        return value

    def test_status_excludes_other_accounts_and_administrator_catalog(self):
        own, other = self.sites()
        state.save(state.ROOT/'catalog.json', dict(secret=dict(plugin_file='private/plugin.php', name='Admin ZIP')))
        with patch.object(host, 'wp_cli', return_value='/usr/local/bin/wp'):
            result = self.api('status')
        self.assertEqual(list(result['inventory']['sites']), [own['id']])
        self.assertEqual(result['inventory']['errors'], [])
        self.assertEqual(result['packages'], [])
        self.assertNotIn(other['domain'], json.dumps(result))
        self.assertEqual(result['library_path'], '/nonexistent/.masswpupdate/premium')

    def test_account_cannot_promote_itself_to_administrator(self):
        with self.assertRaises(PermissionError):
            engine.dispatch(dict(actor='nobody', admin=True, action='status'))

    def test_suspended_account_cannot_access_any_workspace(self):
        with patch.object(hestia, 'cli', return_value=dict(nobody=dict(ROLE='user', SUSPENDED='yes'))):
            with self.assertRaises(PermissionError): self.api('status')

    def test_scoped_native_discovery_never_lists_all_accounts(self):
        import pwd
        replies = dict(nobody=dict(ROLE='user', SUSPENDED='no'), daemon=dict(ROLE='user', SUSPENDED='no'))
        with patch.object(hestia, 'cli', return_value=replies) as cli:
            self.assertEqual([row['user'] for row in hestia.accounts('nobody')], ['nobody'])
        cli.assert_called_once_with('v-list-user', 'nobody', 'json')

    def test_update_cannot_target_a_foreign_site(self):
        own, other = self.sites()
        with patch.object(os, 'posix_spawn', return_value=123):
            with self.assertRaisesRegex(ValueError, 'Select sites'):
                self.api('update', sites=[other['id']], options={key:True for key in jobs.OPTIONS})
            result = self.api('update', sites=[own['id']], options={key:True for key in jobs.OPTIONS})
        request = state.read(jobs.directory(result['job']['id'])/'request.json')
        self.assertEqual(request['scope'], 'nobody')
        self.assertEqual(request['packages'], {})
        self.assertEqual(request['sites'], [own])

    def test_foreign_jobs_cannot_be_read_cancelled_or_downloaded(self):
        own, other = self.sites()
        value = self.job('c'*32, 'daemon', other, 'running')
        state.save(state.ROOT/'latest.json', dict(id=value['id']))
        for action, extra in [('job_details', {}), ('cancel', {}),
                              ('download_prepare', dict(site=other['id'], name='manifest.json'))]:
            with self.subTest(action=action), self.assertRaises(PermissionError):
                self.api(action, job=value['id'], **extra)
        self.assertFalse((jobs.directory(value['id'])/'cancel.json').exists())

    def test_history_and_busy_status_do_not_disclose_other_jobs(self):
        own, other = self.sites()
        self.job('c'*32, 'nobody', own)
        self.job('d'*32, None, other)
        self.job('e'*32, 'daemon', other)
        running = self.job('f'*32, 'daemon', other, 'running')
        state.save(state.ROOT/'latest.json', dict(id=running['id']))
        self.assertEqual([j['id'] for j in self.api('history')['jobs']], ['c'*32])
        status = self.api('job_status')
        self.assertEqual(status, dict(ok=True, job=None, busy=True))

    def test_job_scope_does_not_authorize_a_foreign_snapshot(self):
        own, other = self.sites()
        value = self.job('d'*32, 'nobody', other)
        with self.assertRaises(PermissionError): self.api('job_details', job=value['id'])

    def test_foreign_backups_cannot_be_deleted(self):
        own, other = self.sites()
        with patch.object(host, 'backup_task') as backup:
            with self.assertRaisesRegex(ValueError, 'Select a site'):
                self.api('delete_backups', site=other['id'])
            backup.assert_not_called()

    def test_settings_remain_separate_for_users_and_administrators(self):
        options = {key:False for key in jobs.OPTIONS}
        jobs.save_settings({key:True for key in jobs.OPTIONS}, 3)
        self.api('save_settings', options=options, keep_backups=2)
        with state.scoped('nobody'): self.assertEqual(jobs.settings()['options'], options)
        with state.scoped('daemon'): self.assertTrue(jobs.settings()['options']['themes'])
        self.assertEqual(jobs.settings()['keep_backups'], 3)

    def test_foreign_upload_identity_cannot_be_consumed(self):
        result = self.api('upload_begin', size=100)
        with self.assertRaises(FileNotFoundError):
            self.api('upload_abort', actor='daemon', upload=result['upload'])
        self.assertTrue((state.ROOT/'accounts/nobody/uploads'/result['upload']/'request.json').exists())
        self.api('upload_abort', upload=result['upload'])

    def test_personal_catalog_does_not_replace_or_remove_admin_zip(self):
        admin = catalog.commit(backend.plugin_zip(self.base/'admin.zip', version='9.0'))
        calls = []
        def storage(operation, record, source=None, output=None):
            calls.append((state.account(), operation, record))
            return dict(removed=1, warnings=[]) if operation == 'remove' else dict(stored=True)
        with patch.object(host, 'library_task', side_effect=storage):
            with state.scoped('nobody'):
                user = catalog.commit(backend.plugin_zip(self.base/'personal.zip', version='2.0'))
                self.assertEqual(catalog.entries()[user['slug']]['version'], '2.0')
                self.assertEqual(catalog.remove(user['slug'])['removed'], 1)
            with state.scoped('daemon'): self.assertEqual(catalog.entries(), {})
        self.assertTrue(catalog.package(admin).exists())
        self.assertEqual(catalog.entries()[admin['slug']]['version'], '9.0')
        self.assertEqual([c[:2] for c in calls], [('nobody','store'), ('nobody','remove')])

    def test_personal_package_is_verified_and_staging_is_removed(self):
        source = backend.plugin_zip(self.base/'user.zip')
        record = catalog.inspect(source)
        def storage(operation, request, source=None, output=None): output.write(self.payload)
        with state.scoped('nobody'), patch.object(host, 'library_task', side_effect=storage):
            self.payload = source.read_bytes()
            with catalog.open_package(record) as path:
                self.assertEqual(path.read_bytes(), self.payload)
                temporary = path
            self.assertFalse(temporary.exists())
            self.payload = backend.plugin_zip(self.base/'different.zip', version='99.0').read_bytes()
            with self.assertRaisesRegex(ValueError, 'changed during transfer'):
                with catalog.open_package(record): self.fail('Changed package was accepted')
            self.assertEqual(list((state.data_root()/'packages').iterdir()), [])

    def test_library_accepts_any_version_for_admin_and_user(self):
        def storage(operation, record, source=None, output=None): return dict(stored=True)
        for scope in (None, 'nobody'):
            with self.subTest(scope=scope), state.scoped(scope), patch.object(host, 'library_task', side_effect=storage), \
                 patch.object(host, 'compare', side_effect=AssertionError('Library uploads must not compare versions')):
                latest = catalog.commit(backend.plugin_zip(self.base/'new.zip', version='10.0'))
                older = catalog.commit(backend.plugin_zip(self.base/'old.zip', version='2.0'), expected=latest['slug'])
                self.assertEqual(catalog.entries()[latest['slug']]['version'], '2.0')
                self.assertEqual(catalog.entries()[latest['slug']]['sha256'], older['sha256'])
                # Explicit replacement with the same version remains possible.
                self.assertEqual(catalog.commit(backend.plugin_zip(self.base/'same.zip', version='2.0'),
                                               expected=latest['slug'])['version'], '2.0')

    def test_pending_entry_is_registered_only_in_its_account(self):
        plugin = dict(file='paid/plugin.php', name='Paid', version='1')
        with state.scoped('nobody'):
            catalog.register_pending(plugin, dict(id='a'*32), 'License expired')
            self.assertIn('paid', catalog.entries())
        with state.scoped('daemon'): self.assertEqual(catalog.entries(), {})
        self.assertEqual(catalog.entries(), {})

    def test_late_updater_version_decision_preserves_manual_upgrade(self):
        record = catalog.commit(backend.plugin_zip(self.base/'package.zip', version='2.0'))
        site = dict(id='a'*32, owner='nobody', domain='own.example.test', uid=65534, gid=65534)
        before = dict(core='7.0', php='8.3', plugins=[dict(file=record['plugin_file'], version='1.0')])
        after = dict(core='7.0', php='8.3', plugins=[dict(file=record['plugin_file'], version='5.0')])
        request = dict(options={key:key=='premium' for key in jobs.OPTIONS}, packages={record['slug']:record})
        with patch.object(host,'refresh_site'), patch.object(host,'work',return_value=self.base), patch.object(host,'cleanup'), \
             patch.object(host,'inventory',side_effect=[before,before,after]), \
             patch.object(host,'install_premium',return_value=dict(installed=False,reason='installed version 5.0 is current or newer')) as install:
            result = jobs.update_site(site,request,self.base,lambda message:None)
        install.assert_called_once()
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['actions'], [])
        self.assertIn('5.0', result['skipped'][0])

    def test_scoped_scan_passes_only_its_owner_to_discovery(self):
        with patch.object(os, 'posix_spawn', return_value=123):
            job = self.api('scan')['job']
        with patch.object(host, 'discover', return_value=dict(sites={}, errors=[])) as discover:
            jobs.worker(job['id'])
        self.assertEqual(discover.call_args.args[1], 'nobody')
        self.assertTrue((state.ROOT/'accounts/nobody/inventory.json').exists())
        self.assertFalse((state.ROOT/'inventory.json').exists())


if __name__ == '__main__': unittest.main()
