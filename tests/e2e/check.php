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
        $extra = array_count_values($got); foreach ($exp['attachment_sizes'] as $v) { if (isset($extra[$v]) && --$extra[$v] === 0) unset($extra[$v]); }
        $fail[] = 'attachment sizes differ from generated: '.array_sum($miss).' expected sizes missing in DB (e.g. '.implode(',', array_slice(array_keys($miss), 0, 5)).'), '.array_sum($extra).' stored sizes not expected (e.g. '.implode(',', array_slice(array_keys($extra), 0, 5)).')';
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
// V>=7 theme (malformed MIME): conversations per malformed kind (marker MAL-<kind>-<i>-<j> in the subject), so a failing kind is named instead of only shifting the totals.
if (!empty($exp['malformed_counts'])) {
    $seen = array_fill_keys(array_keys($exp['malformed_counts']), 0);
    foreach (DB::table('conversations')->where('subject', 'like', '%MAL-%')->pluck('subject') as $subject) {
        if (preg_match('/MAL-([a-z0-9]+)-\d+-\d+/', $subject, $m) && isset($seen[$m[1]])) $seen[$m[1]]++;
    }
    foreach ($exp['malformed_counts'] as $kind => $n) {
        if ($seen[$kind] !== $n) $fail[] = "malformed kind '$kind': $seen[$kind] conversations != expected $n";
    }
    // Message::decodeString() strips NUL bytes (#5292): none may reach the stored bodies.
    $nul = DB::table('threads')->whereRaw('LOCATE(CHAR(0), body) > 0')->count();
    if ($nul) $fail[] = "$nul thread bodies contain NUL bytes";
}
// V>=8 theme (one mail to several mailboxes, same sender in all mailboxes): per fan-out marker FAN-<i>-<j> and mailbox, conversations and threads (a reply joins the
// conversation of ITS mailbox; a mailbox only cc'd on the reply opens a new "Re:" conversation), see gen.py. Whatever mailbox fetched first, the result must be the same.
if (!empty($exp['fan_groups'])) {
    $got = [];
    $convRows = DB::table('conversations')->join('mailboxes', 'mailboxes.id', '=', 'conversations.mailbox_id')->where('conversations.subject', 'like', '%FAN-%')
        ->select('conversations.id', 'conversations.subject', 'mailboxes.email')->get();
    $tcount = [];
    foreach (array_chunk($convRows->pluck('id')->all(), 500) as $ids) {
        $tcount += DB::table('threads')->whereIn('conversation_id', $ids)->select('conversation_id', DB::raw('count(*) as c'))->groupBy('conversation_id')->pluck('c', 'conversation_id')->all();
    }
    foreach ($convRows as $r) {
        if (!preg_match('/FAN-(\d+-\d+)/', $r->subject, $m)) continue;
        $e = &$got['FAN-'.$m[1]][$r->email]; $e = $e ?: [0, 0]; $e[0]++; $e[1] += (int) ($tcount[$r->id] ?? 0); unset($e);
    }
    $bad = [];
    foreach ($exp['fan_groups'] as $marker => $boxes) {
        $g = $got[$marker] ?? []; ksort($g); ksort($boxes);
        if ($g !== $boxes) {
            $diff = [];
            foreach ($boxes + $g as $mb => $_) { if (($g[$mb] ?? [0, 0]) !== ($boxes[$mb] ?? [0, 0])) $diff[] = str_replace('@test.local', '', $mb).' '.json_encode($g[$mb] ?? [0, 0]).' != '.json_encode($boxes[$mb] ?? [0, 0]); }
            $bad[] = "$marker (".($exp['fan_kinds'][$marker] ?? '?')."): ".implode(', ', array_slice($diff, 0, 4));
        }
    }
    if ($bad) $fail[] = count($bad).' of '.count($exp['fan_groups']).' fan-out groups wrong [mailbox [convs,threads] got != expected] (e.g. '.implode(' | ', array_slice($bad, 0, 3)).')';
    if ($bad) fwrite(STDERR, "fan-out detail:\n  ".implode("\n  ", $bad)."\n");
}
// Bulk senders write one mail into every mailbox: one customer each, one conversation per mailbox.
if (!empty($exp['burst_senders'])) {
    $gotB = DB::table('conversations')->join('emails', 'emails.customer_id', '=', 'conversations.customer_id')->where('emails.email', 'like', 'bulk%@bulk.example')
        ->select('emails.email', DB::raw('count(*) as c'))->groupBy('emails.email')->pluck('c', 'emails.email')->all();
    foreach ($exp['burst_senders'] as $addr => $n) {
        if ((int) ($gotB[$addr] ?? 0) !== $n) $fail[] = "bulk sender $addr has ".(int) ($gotB[$addr] ?? 0)." conversations != expected $n";
        $c = DB::table('emails')->where('email', $addr)->count();
        if ($c !== 1) $fail[] = "bulk sender $addr has $c customer emails != 1";
    }
}
// V>=9 theme (machine mail): per kind (header X-E2E-Kind: [kind]) the conversations it opened (first thread) and the threads it added, see gen.py. Auto-replies and out-of-office
// loops join the conversation of their ticket (0 conversations); bounces never thread, not even with an In-Reply-To of a known ticket (conversations == threads) and are flagged
// is_bounce in send_status_data; nothing else is flagged.
if (!empty($exp['machine_kinds'])) {
    $bounceKinds = ['ndr', 'ndrplain', 'nullpath'];
    $bad = [];
    foreach ($exp['machine_kinds'] as $kind => list($eConv, $eThr)) {
        $like = '%X-E2E-Kind: ['.$kind.']%';
        $gConv = DB::table('threads')->where('first', 1)->where('headers', 'like', $like)->count();
        $gThr = DB::table('threads')->where('headers', 'like', $like)->count();
        $flag = DB::table('threads')->where('headers', 'like', $like)->where('send_status_data', 'like', '%"is_bounce":true%')->count();
        $eFlag = in_array($kind, $bounceKinds) ? $eThr : 0;
        if ($gConv !== $eConv || $gThr !== $eThr) $bad[] = "$kind [convs,threads] [$gConv,$gThr] != [$eConv,$eThr]";
        if ($flag !== $eFlag) $bad[] = "$kind: $flag threads flagged is_bounce != $eFlag";
    }
    if ($bad) $fail[] = 'machine mail: '.implode('; ', $bad);
}
// Mailing lists: per post marker LST-<i>-<j> and subscriber mailbox exactly one conversation holding the post and all its replies.
if (!empty($exp['list_groups'])) {
    $got = [];
    $convRows = DB::table('conversations')->join('mailboxes', 'mailboxes.id', '=', 'conversations.mailbox_id')->where('conversations.subject', 'like', '%LST-%')
        ->select('conversations.id', 'conversations.subject', 'mailboxes.email')->get();
    $tcount = [];
    foreach (array_chunk($convRows->pluck('id')->all(), 500) as $ids) {
        $tcount += DB::table('threads')->whereIn('conversation_id', $ids)->select('conversation_id', DB::raw('count(*) as c'))->groupBy('conversation_id')->pluck('c', 'conversation_id')->all();
    }
    foreach ($convRows as $r) {
        if (!preg_match('/LST-(\d+-\d+)/', $r->subject, $m)) continue;
        $e = &$got['LST-'.$m[1]][$r->email]; $e = $e ?: [0, 0]; $e[0]++; $e[1] += (int) ($tcount[$r->id] ?? 0); unset($e);
    }
    $bad = [];
    foreach ($exp['list_groups'] as $marker => $boxes) {
        $g = $got[$marker] ?? []; ksort($g); ksort($boxes);
        if ($g !== $boxes) $bad[] = $marker.' got '.json_encode($g).' != '.json_encode($boxes);
    }
    if ($bad) { $fail[] = count($bad).' of '.count($exp['list_groups']).' mailing-list threads wrong [mailbox [convs,threads]] (e.g. '.implode(' | ', array_slice($bad, 0, 3)).')'; fwrite(STDERR, "list detail:\n  ".implode("\n  ", $bad)."\n"); }
}
// V>=10 theme (forwards / @fwd, mails from a mailbox address, same Message-ID twice, agents writing by email): per kind (header X-E2E-Kind: [t10-<kind>]) the conversations opened and threads
// added, and per marker T10-<i>-<j> the (mailbox, customer_email, subject) of every conversation: @fwd replaces sender and subject, other forwards keep the forwarder and "Fwd:", dropped mails
// (invalid notification hash) leave nothing behind. Nothing of this theme is a bounce.
if (!empty($exp['t10_kinds'])) {
    $bad = [];
    foreach ($exp['t10_kinds'] as $kind => list($eConv, $eThr)) {
        $like = '%X-E2E-Kind: [t10-'.$kind.']%';
        $gConv = DB::table('threads')->where('first', 1)->where('headers', 'like', $like)->count();
        $gThr = DB::table('threads')->where('headers', 'like', $like)->count();
        if ($gConv !== $eConv || $gThr !== $eThr) $bad[] = "$kind [convs,threads] [$gConv,$gThr] != [$eConv,$eThr]";
    }
    $flag = DB::table('threads')->where('headers', 'like', '%X-E2E-Kind: [t10-%')->where('send_status_data', 'like', '%"is_bounce":true%')->count();
    if ($flag) $bad[] = "$flag t10 threads flagged is_bounce";
    $got = [];
    foreach (DB::table('conversations')->join('mailboxes', 'mailboxes.id', '=', 'conversations.mailbox_id')->where('conversations.subject', 'like', '%T10-%')
        ->select('conversations.subject', 'conversations.customer_email', 'mailboxes.email')->get() as $r) {
        if (preg_match('/T10-(\d+-\d+)/', $r->subject, $m)) $got['T10-'.$m[1]][] = [$r->email, $r->customer_email, $r->subject];
    }
    $badm = [];
    foreach ($exp['t10_convs'] + array_fill_keys(array_keys($got), []) as $marker => $rows) {
        $g = $got[$marker] ?? []; sort($g); $e = $exp['t10_convs'][$marker] ?? []; sort($e);
        if ($g !== $e) $badm[] = $marker.' got '.json_encode($g).' != '.json_encode($e);
    }
    if ($badm) { $bad[] = count($badm).' of '.count($exp['t10_convs']).' t10 markers wrong [mailbox, customer_email, subject] (e.g. '.implode(' | ', array_slice($badm, 0, 3)).')'; fwrite(STDERR, "t10 detail:\n  ".implode("\n  ", $badm)."\n"); }
    if ($bad) $fail[] = 'forward/self/agent mail: '.implode('; ', $bad);
}
// Two-phase case agentreply: agents answered notifications by email. Replies with a valid hash become message threads (created_by_user_id = the agent) of the conversation they replied to,
// a forwarded notification into another mailbox opens a conversation, an invalid hash leaves nothing.
if (!empty($exp['agent_reply_checks'])) {
    $bad = [];
    foreach ($exp['agent_reply_checks'] as list($mid, $convId, $userId, $type)) {
        $t = DB::table('threads')->where('message_id', $mid)->first();
        if ($type === 'none') { if ($t) $bad[] = "$mid imported although dropped"; continue; }
        if (!$t) { $bad[] = "$mid missing"; continue; }
        if ($type === 'reply' && ((int) $t->conversation_id !== $convId || (int) $t->type !== App\Thread::TYPE_MESSAGE || (int) $t->created_by_user_id !== $userId)) $bad[] = "$mid: conv {$t->conversation_id}/type {$t->type}/user {$t->created_by_user_id} != $convId/message/$userId";
        if ($type === 'fwd' && ((int) $t->conversation_id === $convId || (int) $t->type !== App\Thread::TYPE_CUSTOMER || (int) $t->first !== 1)) $bad[] = "$mid: forwarded notification should open a new conversation (conv {$t->conversation_id}, type {$t->type}, first {$t->first})";
    }
    $nMsg = DB::table('threads')->where('type', App\Thread::TYPE_MESSAGE)->count();
    $eMsg = count(array_filter($exp['agent_reply_checks'], function ($c) { return $c[3] === 'reply'; }));
    if ($nMsg !== $eMsg) $bad[] = "$nMsg agent message threads != expected $eMsg";
    if ($bad) $fail[] = count($bad).' agent-reply problems (e.g. '.implode('; ', array_slice($bad, 0, 4)).')';
}
if ($dupMsg) $fail[] = "$dupMsg duplicated message_id values in threads";
if ($dupMail) $fail[] = "$dupMail duplicated customer emails";
if ($orphans) $fail[] = "$orphans conversations without customer";
printf("conversations=%d/%d threads=%d/%d customers=%d/%d attachments=%d/%d dupMsgId=%d dupEmail=%d orphans=%d\n", $convs, $exp['conversations'], $threads, $exp['threads'], $custs, $exp['customers'], $atts, $exp['attachments'], $dupMsg, $dupMail, $orphans);
if ($fail) { fwrite(STDERR, "FAIL: ".implode("; ", $fail)."\n"); exit(1); }
echo "OK\n";
