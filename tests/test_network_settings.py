import json
import os
import socket
import subprocess
import sys
import unittest


# Fresh processes prevent the startup policy and urllib3 global flag from
# leaking between cases or changing the parent test runner's networking.
PROBE = r'''
import asyncio
import json
import os
import sys
from unittest.mock import patch
import requests
from typer.testing import CliRunner

baseline = requests.packages.urllib3.util.connection.HAS_IPV6
if os.environ.get('TEST_NO_IPV6'):
    baseline = requests.packages.urllib3.util.connection.HAS_IPV6 = False
mode, *args = sys.argv[1:]
report = {'baseline': baseline}

async def inspect_network():
    from blrec.bili import net
    connector = net.get_connector()
    try:
        report.update(family=int(connector.family), limit=connector.limit,
                      ipv6=requests.packages.urllib3.util.connection.HAS_IPV6)
    finally:
        await net.close_connector()

if mode == 'cli':
    from blrec.cli.main import cli
    with patch('blrec.cli.main.uvicorn.run',
               side_effect=lambda *a, **kw: asyncio.run(inspect_network())) as run:
        result = CliRunner().invoke(cli, args)
        report.update(exit=result.exit_code, output=result.output,
                      started=run.called)
else:
    try:
        asyncio.run(inspect_network())
    except ValueError as exc:
        report['error'] = str(exc)
report['env'] = os.environ.get('BLREC_IPV4')
print(json.dumps(report))
'''


class NetworkSettingsTests(unittest.TestCase):
    def probe(self, value, *args, mode='cli', no_ipv6=False):
        env = dict(os.environ)
        env.pop('BLREC_IPV4', None)
        env.pop('TEST_NO_IPV6', None)
        env['PYTHONPATH'] = os.pathsep.join(sys.path)
        if value is not None:
            env['BLREC_IPV4'] = value
        if no_ipv6:
            env['TEST_NO_IPV6'] = '1'
        result = subprocess.run(
            [sys.executable, '-c', PROBE, mode, *args], env=env,
            capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(result.stdout)

    def assert_policy(self, report, forced):
        self.assertEqual(report['family'], int(socket.AF_INET) if forced else 0)
        self.assertEqual(report['ipv6'], False if forced else report['baseline'])
        self.assertEqual(report['limit'], 200)

    def test_cli_default_preserves_environment(self):
        for value, forced in ((None, False), ('0', False), ('False', False), ('1', True)):
            with self.subTest(value=value):
                report = self.probe(value)
                self.assertEqual(report['exit'], 0, report['output'])
                self.assertEqual(report['env'], value)
                self.assert_policy(report, forced)

    def test_explicit_cli_overrides_environment(self):
        for value in (None, '0', '1', 'invalid'):
            for flag, forced in (('--ipv4', True), ('--no-ipv4', False)):
                with self.subTest(value=value, flag=flag):
                    report = self.probe(value, flag)
                    self.assertEqual(report['exit'], 0, report['output'])
                    self.assertEqual(report['env'], '1' if forced else '0')
                    self.assert_policy(report, forced)

    def test_direct_import_parses_false_values(self):
        for value in (None, '', '0', 'false', ' no ', 'OFF', ' FaLsE '):
            with self.subTest(value=value):
                self.assert_policy(self.probe(value, mode='direct'), False)

    def test_direct_import_parses_true_values(self):
        for value in ('1', 'true', ' yes ', 'ON', ' TrUe '):
            with self.subTest(value=value):
                self.assert_policy(self.probe(value, mode='direct'), True)

    def test_invalid_value_stops_before_server_without_echoing_value(self):
        value = 'invalid-private-value'
        report = self.probe(value)
        self.assertEqual(report['exit'], 2)
        self.assertFalse(report['started'])
        self.assertIn('BLREC_IPV4', report['output'])
        self.assertNotIn(value, report['output'])
        error = self.probe(value, mode='direct')['error']
        self.assertIn('BLREC_IPV4', error)
        self.assertNotIn(value, error)

    def test_no_ipv4_does_not_enable_unsupported_ipv6(self):
        self.assert_policy(self.probe('1', '--no-ipv4', no_ipv6=True), False)

    def test_version_and_help_do_not_start_network(self):
        for flag in ('--version', '--help'):
            with self.subTest(flag=flag):
                report = self.probe('invalid', flag)
                self.assertEqual(report['exit'], 0, report['output'])
                self.assertFalse(report['started'])
