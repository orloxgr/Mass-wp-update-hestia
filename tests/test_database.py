"""Native database selection, real process failures and private SQL handoff."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_backend as backend
import account_backups
import hestia
import host
import state


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0, 'Disposable Linux Hestia lab only')
class NativeDatabaseTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown

    def connection(self, **overrides):
        return dict(name='customer_wordpress', host='localhost', port=3306, **overrides)

    def native(self, command, *arguments):
        if command == 'v-list-databases':
            self.assertEqual(arguments, ('customer', 'json'))
            return {'customer_wordpress': dict(TYPE='mysql', HOST='localhost')}
        self.assertEqual((command, arguments), ('v-list-database-host', ('mysql', 'localhost', 'json')))
        return {'localhost': dict(PORT='3306')}

    def test_native_export_matches_account_database_host_and_port(self):
        with patch.object(hestia, 'cli', side_effect=self.native):
            for raw in ('localhost', 'localhost:3306'):
                connection=self.connection();connection['host']=raw
                self.assertEqual(hestia.database_target('customer', connection), 'customer_wordpress')
            for raw in ('localhost:3307', 'external.example.test', '127.0.0.1', 'localhost:/tmp/other.sock'):
                connection=self.connection();connection['host']=raw
                self.assertIsNone(hestia.database_target('customer', connection))

    def test_same_database_name_never_selects_another_account(self):
        with patch.object(hestia, 'cli', return_value={}) as cli:
            self.assertIsNone(hestia.database_target('customer', self.connection()))
        cli.assert_called_once_with('v-list-databases', 'customer', 'json')

    def test_ipv6_database_server_and_nondefault_port_are_matched_explicitly(self):
        connection=dict(name='customer_wordpress', host='[2001:db8::1]:3307', port=3306)
        with patch.object(hestia, 'cli', side_effect=[
                {'customer_wordpress':dict(TYPE='mysql',HOST='2001:db8::1')},
                {'2001:db8::1':dict(PORT='3307')}]):
            self.assertEqual(hestia.database_target('customer', connection), 'customer_wordpress')

    def test_native_failure_is_not_retried_with_wordpress_or_published(self):
        with patch.object(host, 'database_connection', return_value=self.connection()), \
             patch.object(hestia, 'database_target', return_value='customer_wordpress'), \
             patch.object(hestia, 'dump_database', side_effect=RuntimeError('Native database dump failed')), \
             patch.object(host, 'run_as') as run:
            with self.assertRaisesRegex(RuntimeError, 'Native database dump failed'):
                host.backup_task(dict(owner='customer',path='/home/customer/site'), 'archive', self.base, dict(kind='database'))
        run.assert_not_called()

    def test_native_sql_is_handed_to_account_writer_without_php_or_credentials(self):
        sql=b'CREATE TABLE native_backup (id int);\n'
        def dump(owner, database, output):
            self.assertEqual((owner,database), ('customer','customer_wordpress'))
            self.assertEqual(os.fstat(output.fileno()).st_mode & 0o777, 0o600)
            output.write(sql);output.seek(0)
        def run(site, arguments, cwd, **kwargs):
            payload=json.loads(arguments[-1])
            self.assertEqual(payload['database_source'], 'hestia')
            self.assertNotIn('php', payload); self.assertNotIn('wp', payload)
            self.assertNotIn('password', payload)
            self.assertEqual(kwargs['input_source'].read(), sql)
            return '{"ok": true}'
        with patch.object(host, 'database_connection', return_value=self.connection()), \
             patch.object(hestia, 'database_target', return_value='customer_wordpress'), \
             patch.object(hestia, 'dump_database', side_effect=dump), patch.object(host, 'run_as', side_effect=run):
            self.assertEqual(host.backup_task(dict(owner='customer',home='/home/customer',path='/home/customer/site'),
                             'archive',self.base,dict(kind='database')), dict(ok=True))
        self.assertEqual(list((state.ROOT/'backups').iterdir()), [])

    def test_external_database_keeps_wordpress_credentials_and_socket(self):
        with patch.object(host, 'database_connection', return_value=self.connection()), \
             patch.object(hestia, 'database_target', return_value=None), patch.object(hestia, 'dump_database') as dump, \
             patch.object(host, 'database_socket', return_value='/tmp/external.sock'), \
             patch.object(host, 'wp_cli', return_value='/usr/local/bin/wp'), \
             patch.object(host, 'run_as', return_value='{}') as run:
            host.backup_task(dict(owner='customer',home='/home/customer',path='/home/customer/site',php_bin='/usr/bin/php8.3'),
                             'archive',self.base,dict(kind='database'))
        dump.assert_not_called()
        payload=json.loads(run.call_args.args[1][-1])
        self.assertEqual(payload['socket'], '/tmp/external.sock')
        self.assertNotIn('database_source', payload)

    def test_native_command_failure_and_empty_dump_are_real_failures(self):
        root=self.base/'hestia';(root/'bin').mkdir(parents=True)
        command=root/'bin/v-dump-database'
        command.write_text('#!/bin/sh\nprintf "Error: native export authentication failed\\n"\nprintf "native stderr detail\\n" >&2\nexit 15\n')
        command.chmod(0o700)
        with patch.object(hestia,'ROOT',root), tempfile.TemporaryFile() as output:
            with self.assertRaisesRegex(RuntimeError, 'native stderr detail[\\s\\S]*native export authentication failed'):
                hestia.dump_database('customer','customer_wordpress',output)
        command.write_text('#!/bin/sh\nexit 0\n')
        with patch.object(hestia,'ROOT',root), tempfile.TemporaryFile() as output:
            with self.assertRaisesRegex(RuntimeError, 'export is empty'):
                hestia.dump_database('customer','customer_wordpress',output)

    def test_native_sql_zip_is_exact_and_empty_stream_fails(self):
        sql=b'CREATE TABLE exact_target (id int);\n'*1000
        target=io.BytesIO()
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive, \
             patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(sql))):
            account_backups.zip_database(archive,dict(database_source='hestia'))
        with zipfile.ZipFile(target) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read('database.sql'), sql)
        with zipfile.ZipFile(io.BytesIO(),'w') as archive, \
             patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO())):
            with self.assertRaisesRegex(ValueError, 'export is empty'):
                account_backups.zip_database(archive,dict(database_source='hestia'))


if __name__ == '__main__': unittest.main()
