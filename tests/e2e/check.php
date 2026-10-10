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
// Reply-To wins over From as the conversation's sender (processMessage); the generator counts the tickets that carry one.
$replyTo = DB::table('threads')->where('first', 1)->where('from', 'like', '%@replyto.example')->count();
if (isset($exp['reply_to_conversations']) && $replyTo !== $exp['reply_to_conversations']) $fail[] = "reply-to conversations $replyTo != expected {$exp['reply_to_conversations']}";
$upper = DB::table('emails')->whereRaw('BINARY email != LOWER(email)')->count();
if ($upper) $fail[] = "$upper customer emails not lower-cased";
$emptyConv = DB::table('conversations')->whereNotIn('id', DB::table('threads')->select('conversation_id'))->count();
if ($emptyConv) $fail[] = "$emptyConv conversations without threads";
// Attachments: Attachment::create() refuses empty content, so no row may be 0 bytes; every row's file must exist on disk with the recorded size.
$zeroAtt = DB::table('attachments')->where('size', 0)->count();
if ($zeroAtt) $fail[] = "$zeroAtt zero-byte attachments stored";
// The multiset of stored sizes must equal the multiset of decoded attachment sizes the generator wrote (a truncated attachment keeps the count but not the size).
if (isset($exp['attachment_sizes'])) {
    $got = DB::table('attachments')->orderBy('size')->pluck('size')->map(function ($v) { return (int) $v; })->all();
    if ($got !== $exp['attachment_sizes']) {
        $miss = array_count_values($exp['attachment_sizes']); foreach ($got as $v) { if (isset($miss[$v]) && --$miss[$v] === 0) unset($miss[$v]); }
        $fail[] = 'attachment sizes differ from generated: '.array_sum($miss).' expected sizes missing in DB (e.g. '.implode(',', array_slice(array_keys($miss), 0, 5)).')';
    }
}
// Every attachment row belongs to a thread (no thread -> never deleted with its conversation, not shown with its thread).
$orphanAtt = DB::table('attachments')->whereNull('thread_id')->count();
if ($orphanAtt) $fail[] = "$orphanAtt attachments without thread_id";
// Every customer here was created from an address: one without an email row is a leftover of an interrupted Customer::create() (customer saved, email not yet).
$noEmailCust = DB::table('customers')->whereNotExists(function ($q) { $q->select(DB::raw(1))->from('emails')->whereRaw('emails.customer_id = customers.id'); })->count();
if ($noEmailCust) $fail[] = "$noEmailCust customers without any email";
$noFile = 0; $badSize = 0; $noDir = 0;
foreach (DB::table('attachments')->select('id', 'file_name', 'file_dir', 'size')->orderBy('id')->cursor() as $a) {
    if (!$a->file_dir) { $noDir++; continue; }
    $path = App\Attachment::DIRECTORY.DIRECTORY_SEPARATOR.$a->file_dir.$a->file_name;
    if (!App\Attachment::getDisk()->exists($path)) $noFile++;
    elseif (App\Attachment::getDisk()->size($path) != $a->size) $badSize++;
}
if ($noDir || $noFile || $badSize) $fail[] = "attachments: $noDir without file_dir, $noFile files missing on disk, $badSize with wrong size";
// V>=6 theme. Long threads: every reply links via In-Reply-To, so a long thread is one conversation of exactly K+1 threads (gen.py keeps other replies away from it).
if (!empty($exp['long_thread_sizes'])) {
    $n = count($exp['long_thread_sizes']);
    $got = DB::table('threads')->select('conversation_id', DB::raw('count(*) as c'))->groupBy('conversation_id')->orderBy('c', 'desc')->limit($n)->pluck('c')->map(function ($v) { return (int) $v; })->all();
    if ($got !== $exp['long_thread_sizes']) $fail[] = 'longest conversations have '.implode(',', $got).' threads, expected '.implode(',', $exp['long_thread_sizes']);
}
// Huge bodies (1-3MB html) are stored whole: DOM re-serialization of ASCII markup keeps the size (generous 10% margin), nothing else is that big.
if (!empty($exp['huge_bodies'])) {
    $big = DB::table('threads')->whereRaw('LENGTH(body) >= ?', [(int) ($exp['min_huge_len'] * 0.9)])->count();
    if ($big !== $exp['huge_bodies']) $fail[] = "threads with a body >= 90% of the smallest generated huge body: $big != expected {$exp['huge_bodies']}";
}
// Reply separation: the stored body of a reply that quotes its predecessor behind a known separator holds its own text and none of the quoted tokens.
if (!empty($exp['quote_checks'])) {
    $bad = []; $missing = 0;
    foreach (array_chunk($exp['quote_checks'], 200) as $chunk) {
        $rows = DB::table('threads')->whereIn('message_id', array_map(function ($c) { return trim($c[0], '<>'); }, $chunk))->pluck('body', 'message_id')->all();
        foreach ($chunk as list($mid, $own, $forbid)) {
            $body = $rows[trim($mid, '<>')] ?? null;
            if ($body === null) { $missing++; continue; }
            $leak = array_filter($forbid, function ($t) use ($body) { return strpos($body, $t) !== false; });
            if (strpos($body, $own) === false || $leak) $bad[] = $mid.(strpos($body, $own) === false ? ' lost its own text' : ' kept quoted '.implode('/', $leak));
        }
    }
    if ($bad) $fail[] = count($bad).' replies with wrong quote separation (e.g. '.implode('; ', array_slice($bad, 0, 3)).')';
    if ($missing) $fail[] = "$missing quote-check threads not imported";
}
if ($dupMsg) $fail[] = "$dupMsg duplicated message_id values in threads";
if ($dupMail) $fail[] = "$dupMail duplicated customer emails";
if ($orphans) $fail[] = "$orphans conversations without customer";
printf("conversations=%d/%d threads=%d/%d customers=%d/%d attachments=%d/%d dupMsgId=%d dupEmail=%d orphans=%d\n", $convs, $exp['conversations'], $threads, $exp['threads'], $custs, $exp['customers'], $atts, $exp['attachments'], $dupMsg, $dupMail, $orphans);
if ($fail) { fwrite(STDERR, "FAIL: ".implode("; ", $fail)."\n"); exit(1); }
echo "OK\n";
