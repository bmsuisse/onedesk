<?php
// Prints (JSON) what cases/agentreply.sh needs to write valid agent replies: conversations to answer with their first thread, the mailbox it lives in, the
// notification hash md5(thread_id . app.key)[:16], the agents' user ids and the e-mail addresses that are already customers. Usage: php agent_targets.php COUNT
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$want = (int) ($argv[1] ?? 36);
$rows = DB::table('threads as t')->join('conversations as c', 'c.id', '=', 't.conversation_id')->join('mailboxes as m', 'm.id', '=', 'c.mailbox_id')
    ->where('t.first', 1)->where('t.type', App\Thread::TYPE_CUSTOMER)->whereRaw("c.subject REGEXP '^[a-z]+ [0-9]+-[0-9]+$'")   // plain tickets only: markers of fan-out, list, malformed, theme and long-thread conversations must keep their exact thread counts
    ->whereIn('c.id', function ($q) { $q->select('conversation_id')->from('threads')->groupBy('conversation_id')->havingRaw('count(*) = 1'); })->orderBy('t.id')
    ->select('t.id as tid', 'c.id as cid', 'c.number', 'c.subject', 'm.email as mb')->get();
$step = max(1, intdiv($rows->count(), $want));
$out = ['targets' => [], 'users' => [], 'known' => []];
foreach ($rows->values() as $n => $r) {
    if ($n % $step || count($out['targets']) >= $want) continue;
    $out['targets'][] = ['tid' => (int) $r->tid, 'cid' => (int) $r->cid, 'number' => (int) $r->number, 'subject' => $r->subject, 'mb' => $r->mb, 'hash' => MailHelper::getMessageIdHash($r->tid)];
}
foreach (DB::table('users')->where('email', 'like', 'agent%@helpdesk.example')->get() as $u) $out['users'][$u->email] = (int) $u->id;
$out['known'] = DB::table('emails')->where('email', 'like', 'agent%@helpdesk.example')->pluck('email')->all();
$out['customers'] = DB::table('customers')->count();
echo json_encode($out);
