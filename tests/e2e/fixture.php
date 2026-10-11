<?php
// Deterministic web fixture in the e2e DB: wipes conversation data, resets agent1's throwaway password, creates 2 customers and
// 2 conversations (one with a customer thread + an agent reply). Never touches anything but the e2e database. Usage: php fixture.php
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('database.connections.mysql.host') !== 'odtest-db') { fwrite(STDERR, "refusing: not the odtest-db database\n"); exit(2); }

DB::statement('SET FOREIGN_KEY_CHECKS=0');
foreach (['threads', 'conversations', 'customers', 'emails', 'attachments', 'polycast_events', 'send_logs', 'failed_jobs', 'jobs', 'activity_log', 'subscriptions'] as $t) {
    if (Schema::hasTable($t)) DB::table($t)->truncate();
}
DB::statement('SET FOREIGN_KEY_CHECKS=1');

$u = App\User::where('email', 'agent1@helpdesk.example')->first() ?: abort(500, 'run `run.sh up` first (seeds agent1)');
$u->password = bcrypt('secret'); $u->role = App\User::ROLE_ADMIN; $u->first_name = 'Agent'; $u->last_name = 'One'; $u->timezone = 'UTC'; $u->save();
foreach (App\Mailbox::all() as $m) { $m->users()->syncWithoutDetaching([$u->id]); }

$mk = function ($email, $first, $last, $subject, $body) {
    $c = App\Customer::create($email, ['first_name' => $first, 'last_name' => $last]);
    $r = App\Conversation::create(['type' => App\Conversation::TYPE_EMAIL, 'subject' => $subject, 'mailbox_id' => 1, 'source_type' => App\Conversation::SOURCE_TYPE_EMAIL,
        'status' => App\Conversation::STATUS_ACTIVE, 'imported' => true], [['type' => App\Thread::TYPE_CUSTOMER, 'body' => $body, 'imported' => true]], $c);
    return [$c, $r['conversation']];
};
[$c1, $v1] = $mk('anna.customer@example.com', 'Anna', 'Customer', 'Printer on fire', '<p>Hello, the printer is on fire. Please help.</p>');
[$c2, $v2] = $mk('bob.buyer@example.com', 'Bob', 'Buyer', 'Invoice question', '<p>Where is my invoice for October?</p>');
App\Thread::createExtended(['type' => App\Thread::TYPE_MESSAGE, 'body' => '<p>We are on it.</p>', 'created_by_user_id' => $u->id, 'imported' => true], $v1, $c1, true);
$v1->mailbox->updateFoldersCounters();
echo json_encode(['customer1' => $c1->id, 'customer2' => $c2->id, 'conv1' => $v1->id, 'conv2' => $v2->id, 'user' => $u->id, 'mailbox' => 1, 'folder' => (int) App\Folder::where('mailbox_id', 1)->where('type', App\Folder::TYPE_UNASSIGNED)->value('id')]), "\n";
