<?php
// Authentication failures must stop before any native privileged request.
define('MASSWP_PANEL', true);
require dirname(__DIR__) . '/panel/api.php';
function rejects(callable $callback, string $message): void {
    try { $callback(); }
    catch (Throwable $error) {
        if (strpos($error->getMessage(), $message) !== false) return;
        throw $error;
    }
    throw new RuntimeException('Expected request rejection: ' . $message);
}
$_POST = ['payload'=>json_encode(['action'=>'scan'])];
rejects(static fn() => mwu_api('root', 'valid-token', false), 'Session expired');
$_POST['token'] = ['valid-token'];
rejects(static fn() => mwu_api('root', 'valid-token', false), 'Session expired');
$_POST['token'] = 'wrong-token';
rejects(static fn() => mwu_api('root', 'valid-token', false), 'Session expired');
$_POST['token'] = 'valid-token';
rejects(static fn() => mwu_api('root', 'valid-token', true), 'demo mode');
$_POST['payload'] = json_encode(['action'=>'scan','actor'=>'root']);
rejects(static fn() => mwu_api('root', 'valid-token', false), 'Invalid request');
$_POST['payload'] = json_encode(['action'=>'upload_chunk']);
$_FILES = [];
rejects(static fn() => mwu_api('root', 'valid-token', false), 'ZIP chunk');
$_POST = ['mwu_download'=>'1','token'=>'valid-token','payload'=>json_encode(['action'=>'scan'])];
rejects(static fn() => mwu_api('root', 'valid-token', false), 'Invalid download');
echo "Seven native-panel request rejection checks passed.\n";
