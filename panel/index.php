<?php
// Managed by mass-wp-update-hestia
declare(strict_types=1);
$install = '__INSTALL_ROOT__';
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET' && empty($_SERVER['HTTP_REFERER'])) {
    // Hestia's strict GET CSRF policy expects a real same-origin navigation.
    // This public landing exposes no account data and does not bypass it.
    header('Cache-Control: no-store');
    header('Content-Type: text/html; charset=UTF-8');
    echo '<!doctype html><html lang="en"><meta charset="utf-8"><title>Mass WP Update</title><main><h1>Mass WP Update</h1><p><a href="./">Open Mass WP Update</a></p></main></html>';
    exit;
}
$root = '/usr/local/hestia';
chdir($root . '/web');
$TAB = 'WEB';
$panel = new class implements ArrayAccess {
    public function offsetExists(mixed $offset): bool { return true; }
    public function offsetGet(mixed $offset): mixed {
        $name = trim((string)$offset, "'");
        if (!preg_match('/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/D', $name)) return ['SUSPENDED'=>'yes'];
        return get_user_data($name)[$name] ?? ['SUSPENDED'=>'yes'];
    }
    public function offsetSet(mixed $offset, mixed $value): void { throw new LogicException('Read only'); }
    public function offsetUnset(mixed $offset): void { throw new LogicException('Read only'); }
};
require $root . '/web/inc/main.php';
header('Cache-Control: no-store, private');
header('X-Robots-Tag: noindex, nofollow');
header('X-Content-Type-Options: nosniff');
$actor = $_SESSION['user'] ?? '';
$csrf = $_SESSION['token'] ?? '';
$actorData = get_user_data($actor)[$actor] ?? [];
$isAdmin = ($actorData['ROLE'] ?? '') === 'admin' && empty($_SESSION['look']);
$ajax = ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST' && ($_SERVER['HTTP_X_MWU_REQUEST'] ?? '') === '1';
if (!$isAdmin || !is_string($csrf) || $csrf === '') {
    http_response_code(403);
    if ($ajax) { header('Content-Type: application/json'); echo json_encode(['ok'=>false,'error'=>'Hestia administrator access is required.']); }
    else { echo 'Hestia administrator access is required.'; }
    exit;
}
define('MASSWP_PANEL', true);
require $install . '/panel/api.php';
$demo = !empty($read_only);
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (($_POST['mwu_download'] ?? '') === '1') {
        ignore_user_abort(true);
        try { mwu_send_download(mwu_api($actor, $csrf, $demo)); }
        catch (Throwable $error) { http_response_code(400); header('Content-Type: text/plain; charset=UTF-8'); echo $error->getMessage(); }
        exit;
    }
    if (!$ajax) { http_response_code(400); exit; }
    header('Content-Type: application/json; charset=UTF-8');
    try { $result = mwu_api($actor, $csrf, $demo); }
    catch (Throwable $error) { $result = ['ok'=>false,'error'=>$error->getMessage()]; }
    echo json_encode($result, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'GET') { http_response_code(405); exit; }
header('Content-Type: text/html; charset=UTF-8');
$escape = static fn($value) => htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
$headerOwner = $actor;
require $root . '/web/templates/header.php';
$panel = top_panel($headerOwner, $TAB);
echo '<script>document.title="Mass WP Update";</script>';
echo '<div class="toolbar"><div class="toolbar-inner"><div class="toolbar-buttons"><a class="button button-secondary" href="/list/web/">Back</a></div></div></div>';
echo '<div class="container">';
require $install . '/panel/view.php';
echo '</div>';
require $root . '/web/templates/footer.php';
