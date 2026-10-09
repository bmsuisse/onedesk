<?php
// One fetch under the Excimer sampling profiler; prints top functions by self and inclusive time.
// Usage: php profile.php <all|1,2,3> [period_ms=5]
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$opts = ['--days' => 7];
if (($argv[1] ?? 'all') !== 'all') $opts['--mailboxes'] = $argv[1];
$p = new ExcimerProfiler();
$p->setEventType(EXCIMER_REAL);
$p->setPeriod(((float) ($argv[2] ?? 5)) / 1000);
$t = microtime(true);
$p->start();
ob_start(); Artisan::call('freescout:fetch-emails', $opts); ob_end_clean();
$p->stop();
$wall = microtime(true) - $t;
$self = $incl = $where = []; $total = 0;
foreach ($p->getLog() as $entry) {
    $w = $entry->getEventCount(); $total += $w;
    $trace = $entry->getTrace(); $seen = [];
    foreach ($trace as $i => $f) {
        $name = (isset($f['class']) ? $f['class'].'::' : '').($f['function'] ?? '{main}');
        if (!isset($where[$name])) $where[$name] = preg_replace('#^/app/#', '', $f['file'] ?? '?').':'.($f['line'] ?? 0);
        if ($i === 0) $self[$name] = ($self[$name] ?? 0) + $w;
        if (!isset($seen[$name])) { $seen[$name] = 1; $incl[$name] = ($incl[$name] ?? 0) + $w; }   // recursion counted once
    }
}
$show = function ($title, $a) use ($total, $where) {
    arsort($a); printf("\n%s\n", $title);
    foreach (array_slice($a, 0, 25, true) as $n => $c) printf("%6.1f%%  %-70s %s\n", 100 * $c / max(1, $total), substr($n, 0, 70), $where[$n]);
};
printf("wall %.2fs, %d samples @ %sms\n", $wall, $total, $argv[2] ?? 5);
$show('TOP 25 BY SELF TIME', $self);
$show('TOP 25 BY INCLUSIVE TIME', $incl);
