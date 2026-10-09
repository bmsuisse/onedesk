<?php
// Asserts the DB state after a fetch against the counts gen.py computed. Usage: php check.php /path/expected.json
// Exit code 1 + message per failed assertion.
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$exp = json_decode(file_get_contents($argv[1]), true);
$fail = [];
$convs = DB::table('conversations')->count();
$threads = DB::table('threads')->count();
$dupMsg = DB::table('threads')->whereNotNull('message_id')->select('message_id')->groupBy('message_id')->havingRaw('count(*) > 1')->count();
$dupMail = DB::table('emails')->select('email')->groupBy('email')->havingRaw('count(*) > 1')->count();
$orphans = DB::table('conversations')->whereNotIn('customer_id', DB::table('customers')->select('id'))->count();
$custs = DB::table('customers')->count();
$atts = DB::table('attachments')->count();
foreach (['conversations' => $convs, 'threads' => $threads, 'customers' => $custs, 'attachments' => $atts] as $k => $got) {
    if ($got !== $exp[$k]) $fail[] = "$k $got != expected {$exp[$k]}";
}
if ($dupMsg) $fail[] = "$dupMsg duplicated message_id values in threads";
if ($dupMail) $fail[] = "$dupMail duplicated customer emails";
if ($orphans) $fail[] = "$orphans conversations without customer";
printf("conversations=%d/%d threads=%d/%d customers=%d/%d attachments=%d/%d dupMsgId=%d dupEmail=%d orphans=%d\n", $convs, $exp['conversations'], $threads, $exp['threads'], $custs, $exp['customers'], $atts, $exp['attachments'], $dupMsg, $dupMail, $orphans);
if ($fail) { fwrite(STDERR, "FAIL: ".implode("; ", $fail)."\n"); exit(1); }
echo "OK\n";
