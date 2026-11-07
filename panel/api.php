<?php
declare(strict_types=1);
if (!defined('MASSWP_PANEL')) { http_response_code(403); exit; }

function mwu_bridge(array $request): array {
    $identity = bin2hex(random_bytes(32));
    $path = '/run/mass-wp-update-hestia/' . $identity . '.json';
    $payload = json_encode($request, JSON_THROW_ON_ERROR);
    if (strlen($payload) > 1024 * 1024) throw new RuntimeException('Request exceeds 1 MiB.');
    $mask = umask(0077);
    try { $handle = fopen($path, 'x'); }
    finally { umask($mask); }
    if ($handle === false) throw new RuntimeException('Activate Mass WP Update before using it.');
    try {
        $offset = 0;
        while ($offset < strlen($payload)) {
            $written = fwrite($handle, substr($payload, $offset));
            if ($written === false || $written === 0) throw new RuntimeException('Could not send the request.');
            $offset += $written;
        }
        fclose($handle); $handle = null;
        $pipes = [];
        $process = proc_open(['/usr/bin/sudo', '-n', '/usr/local/hestia/bin/v-mass-wp-update-hestia', '--request', $identity],
            [0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']], $pipes);
        if (!is_resource($process)) throw new RuntimeException('Could not start the Hestia worker bridge.');
        fclose($pipes[0]);
        $output = ''; $error = ''; $open = [1=>$pipes[1],2=>$pipes[2]];
        foreach ($open as $pipe) stream_set_blocking($pipe, false);
        while ($open) {
            $ready = array_values($open); $write = null; $except = null;
            if (stream_select($ready, $write, $except, null) === false) continue;
            foreach ($open as $index=>$pipe) {
                if (!in_array($pipe,$ready,true)) continue;
                $chunk = fread($pipe,8192);
                if ($chunk !== false) { if ($index === 1) $output .= $chunk; else $error .= $chunk; }
                if (feof($pipe)) { fclose($pipe); unset($open[$index]); }
            }
        }
        $exit = proc_close($process);
        $result = ['output'=>[$output],'retval'=>$exit];
        $data = json_decode(implode("\n", $result['output'] ?? []), true);
        if (!is_array($data)) throw new RuntimeException('The worker returned an invalid response.');
        if (($data['response'] ?? '') === $identity) {
            $responsePath = '/run/mass-wp-update-hestia/' . $identity . '.response';
            $info = lstat($responsePath);
            if ($info === false || ($info['mode'] & 0170000) !== 0100000 || ($info['mode'] & 0777) !== 0600 || $info['nlink'] !== 1) throw new RuntimeException('Invalid private response file.');
            $data = json_decode(file_get_contents($responsePath), true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($data)) throw new RuntimeException('Invalid worker response.');
        }
        return $data;
    } finally {
        if (is_resource($handle)) fclose($handle);
        if (is_file($path)) unlink($path);
        $responsePath = '/run/mass-wp-update-hestia/' . $identity . '.response';
        if (is_file($responsePath)) unlink($responsePath);
    }
}
function mwu_api(string $actor, string $csrf, bool $demo): array {
    if ($demo) throw new RuntimeException('Changes are unavailable in demo mode.');
    $token = $_POST['token'] ?? null;
    if (!is_string($token) || !hash_equals($csrf, $token)) throw new RuntimeException('Session expired. Reload this page and try again.');
    $payload = $_POST['payload'] ?? '';
    if (!is_string($payload) || strlen($payload) > 1024 * 1024) throw new RuntimeException('Invalid request size.');
    $request = json_decode($payload, true, 32, JSON_THROW_ON_ERROR);
    if (!is_array($request) || isset($request['actor']) || isset($request['admin'])) throw new RuntimeException('Invalid request.');
    if ((($request['action'] ?? '') === 'download_prepare') !== (($_POST['mwu_download'] ?? '') === '1')) throw new RuntimeException('Invalid download request.');
    $part = null;
    try {
        if (($request['action'] ?? '') === 'upload_chunk') {
            $upload = $_FILES['chunk'] ?? null;
            if (!is_array($upload) || ($upload['error'] ?? -1) !== UPLOAD_ERR_OK ||
                !is_int($upload['size']) || $upload['size'] < 1 || $upload['size'] > 1024 * 1024 ||
                !is_uploaded_file($upload['tmp_name'])) throw new RuntimeException('Could not receive the ZIP chunk.');
            $identity = bin2hex(random_bytes(32));
            $part = '/run/mass-wp-update-hestia/' . $identity . '.part';
            $mask = umask(0077);
            try { $handle = fopen($part, 'x'); }
            finally { umask($mask); }
            if ($handle === false) throw new RuntimeException('Could not stage the ZIP chunk.');
            try {
                $source = fopen($upload['tmp_name'], 'rb');
                if ($source === false) throw new RuntimeException('Could not read the ZIP chunk.');
                try {
                    if (stream_copy_to_stream($source, $handle, 1024 * 1024 + 1) !== $upload['size']) throw new RuntimeException('ZIP chunk size mismatch.');
                } finally { fclose($source); }
            } finally { fclose($handle); }
            $request['part'] = $identity;
        } elseif (!empty($_FILES)) throw new RuntimeException('Unexpected upload.');
        $request['actor'] = $actor;
        $request['admin'] = true;
        return mwu_bridge($request);
    } finally {
        if ($part !== null && is_file($part)) unlink($part);
    }
}
function mwu_send_download(array $result): void {
    if (empty($result['ok'])) throw new RuntimeException($result['error'] ?? 'Could not prepare backup.');
    $download = $result['download'] ?? [];
    $token = $download['token'] ?? '';
    $filename = $result['filename'] ?? '';
    if (!is_string($token) || !preg_match('/^[0-9a-f]{64}$/D', $token) || !is_string($filename) || !preg_match('/^[0-9a-f]{32}-(plugins\.tar\.gz|themes\.tar\.gz|database\.sql|(?:plugins|themes|database)\.zip|manifest\.json)$/D', $filename)) throw new RuntimeException('Invalid backup response.');
    $path = '/var/lib/mass-wp-update-hestia-downloads/' . $token . '.download';
    $handle = null;
    try {
        $info = lstat($path);
        if ($info === false || ($info['mode'] & 0170000) !== 0100000 || ($info['mode'] & 0777) !== 0600 || $info['nlink'] !== 1 || $info['uid'] !== $download['uid'] || $info['size'] !== $download['bytes']) throw new RuntimeException('Invalid backup staging file.');
        $handle = fopen($path, 'rb');
        if ($handle === false) throw new RuntimeException('Could not open backup.');
        if (fstat($handle)['ino'] !== $info['ino']) throw new RuntimeException('Backup staging file changed.');
        while (ob_get_level()) { if (!ob_end_clean()) break; }
        header('Content-Type: application/octet-stream');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        header('Content-Length: ' . $info['size']);
        header('Cache-Control: no-store');
        header('X-Content-Type-Options: nosniff');
        while (!feof($handle)) {
            $block = fread($handle, 1024 * 1024);
            if ($block === false) throw new RuntimeException('Could not read backup.');
            echo $block; flush();
            if (connection_aborted()) break;
        }
    } finally {
        if (is_resource($handle)) fclose($handle);
        if (is_file($path)) unlink($path);
    }
}
