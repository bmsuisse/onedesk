<?php
// Drives every outgoing-mail path of the app exactly the way the controller/listeners do (events -> sync queue -> mailables) against the mail sink.
// Usage: php send.php <smtp|mail|system>   (fixture.php must have run). Sink: smtp = odtest-smtp:2525 (container), mail() = sendmail stub (-d sendmail_path).
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use App\{Mailbox, Conversation, Thread, Customer, User, Option, Attachment, Subscription};
$mode = $argv[1] ?? 'smtp';
$mb = Mailbox::find(1); $agent = User::find(1);
$mb->from_name = Mailbox::FROM_NAME_CUSTOM; $mb->from_name_custom = 'Support Zürich'; $mb->signature = '<p>-- <br>Agent One, OneDesk</p>';
$mb->auto_reply_enabled = true; $mb->auto_reply_subject = 'We got your request: {%subject%}'; $mb->auto_reply_message = '<p>Hello {%customer.fullName%}, this is an automatic reply.</p>';
if ($mode === 'smtp' || $mode === 'system') {
    $mb->out_method = Mailbox::OUT_METHOD_SMTP; $mb->out_server = 'odtest-smtp'; $mb->out_port = 2525; $mb->out_username = 'smtp-user@test.local'; $mb->out_password = 'smtp-pass'; $mb->out_encryption = Mailbox::OUT_ENCRYPTION_NONE;
} else {
    $mb->out_method = Mailbox::OUT_METHOD_PHP_MAIL;
}
$mb->save();
// System mail (user notifications, test mail, invites) goes through the options-based driver.
Option::set('mail_driver', $mode === 'mail' ? 'mail' : 'smtp'); Option::set('mail_host', 'odtest-smtp'); Option::set('mail_port', 2525); Option::set('mail_encryption', ''); Option::set('mail_username', ''); Option::set('mail_from', 'system@test.local');

$conv = Conversation::find(1); $cust = Customer::find(1);
$conv->subject = 'Drucker brennt – Größe über Ärger'; $conv->save();
$first = $conv->threads()->where('type', Thread::TYPE_CUSTOMER)->first();
$first->message_id = 'cust-orig-1@example.com'; $first->save();

$which = $argv[2] ?? 'all';
$run = fn ($n) => $which === 'all' || $which === $n;

if ($run('reply')) {
    // agent reply with an attachment + unicode body; createExtended() fires UserReplied itself (sync queue => SendReplyToCustomer job runs inline, like after the undo timer).
    Thread::createExtended(['type' => Thread::TYPE_MESSAGE, 'body' => '<p>Hallo Anna, wir kümmern uns darum – Größe ändern ✓</p>', 'created_by_user_id' => $agent->id, 'imported' => false,
        'attachments' => [['file_name' => 'Rechnung Übersicht.txt', 'mime_type' => 'text/plain', 'data' => base64_encode("Hello attachment\n")]]], $conv, $cust, true);
}
if ($run('autoreply')) {
    // new conversation from a customer -> auto reply (+ new-conversation notification to subscribed agents)
    $c2 = Customer::find(2);
    $r = Conversation::create(['type' => Conversation::TYPE_EMAIL, 'subject' => 'Rechnung Frage', 'mailbox_id' => 1, 'source_type' => Conversation::SOURCE_TYPE_EMAIL, 'status' => Conversation::STATUS_ACTIVE, 'imported' => false],
        [['type' => Thread::TYPE_CUSTOMER, 'body' => '<p>Wo ist meine Rechnung?</p>', 'imported' => false]], $c2);
    $th = $r['thread']; $th->message_id = 'cust-orig-2@example.com'; $th->save();
    event(new App\Events\CustomerCreatedConversation($r['conversation']->fresh(), $th->fresh()));
}
if ($run('notify')) {
    // agent2 follows everything -> notification mail (UserNotification mailable) when the customer replies
    $a2 = User::where('email', 'agent2@helpdesk.example')->first();
    DB::table('subscriptions')->where('user_id', $a2->id)->delete();
    foreach ([Subscription::EVENT_CUSTOMER_REPLIED_TO_UNASSIGNED, Subscription::EVENT_NEW_CONVERSATION] as $ev) {
        DB::table('subscriptions')->insert(['user_id' => $a2->id, 'medium' => Subscription::MEDIUM_EMAIL, 'event' => $ev]);
    }
    $a2->mailboxes()->syncWithoutDetaching([1]);
    $th = Thread::createExtended(['type' => Thread::TYPE_CUSTOMER, 'body' => '<p>Es brennt immer noch!</p>', 'customer_id' => $cust->id, 'imported' => false], $conv->fresh(), $cust, true);
    $th->message_id = 'cust-reply-1@example.com'; $th->save();
    Subscription::processEvents();
}
if ($run('test')) {
    echo 'testmail: ', json_encode(\MailHelper::sendTestMail('tester@example.com', $mode === 'system' ? null : $mb)), "\n";
}
