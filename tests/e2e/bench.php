<?php
// One fetch with metrics as JSON. Usage: php bench.php <all|1,2,3>
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$q = 0; $qt = 0.0; $by = [];
DB::listen(function ($e) use (&$q, &$qt, &$by) {
    $q++; $qt += $e->time;
    $sig = substr(preg_replace('/\s+/', ' ', preg_replace('/\b\d+\b|\'[^\']*\'|\([?, ]+\)/', '?', $e->sql)), 0, 120);
    $by[$sig] = ($by[$sig] ?? ['n' => 0, 'ms' => 0]); $by[$sig]['n']++; $by[$sig]['ms'] += $e->time;
});
$opts = ['--days' => 7];
if (($argv[1] ?? 'all') !== 'all') $opts['--mailboxes'] = $argv[1];
$t = microtime(true); $r0 = getrusage();
ob_start(); Artisan::call('freescout:fetch-emails', $opts); $out = ob_get_clean();
$r1 = getrusage(); $wall = microtime(true) - $t;
$cpu = ($r1['ru_utime.tv_sec'] - $r0['ru_utime.tv_sec']) + ($r1['ru_utime.tv_usec'] - $r0['ru_utime.tv_usec']) / 1e6
     + ($r1['ru_stime.tv_sec'] - $r0['ru_stime.tv_sec']) + ($r1['ru_stime.tv_usec'] - $r0['ru_stime.tv_usec']) / 1e6;
uasort($by, function ($a, $b) { return $b['ms'] <=> $a['ms']; });
$threads = DB::table('threads')->count();
echo json_encode([
    'threads' => $threads, 'wall_s' => round($wall, 2), 'cpu_s' => round($cpu, 2), 'db_s' => round($qt / 1000, 2),
    'queries' => $q, 'queries_per_mail' => $threads ? round($q / $threads, 1) : null, 'peak_mem_mb' => round(memory_get_peak_usage(true) / 1048576, 1),
    'errors' => preg_match_all('/error|exception/i', $out),
    'top_queries' => array_slice($by, 0, 10, true),
], JSON_PRETTY_PRINT), "\n";
