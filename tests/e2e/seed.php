<?php
// Creates N IMAP mailboxes (mb1..mbN@test.local) pointing at the mock Dovecot. Usage: php seed.php N
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
App\Mailbox::query()->delete();
for ($i = 1; $i <= (int) $argv[1]; $i++) {
    $m = new App\Mailbox();
    $m->forceFill(['name' => "MB$i", 'email' => "mb$i@test.local", 'in_server' => getenv('E2E_IMAP_HOST'), 'in_port' => 143,
        'in_username' => "mb$i@test.local", 'in_protocol' => 1, 'in_encryption' => 1, 'in_validate_cert' => 0, 'out_method' => 1, 'aliases' => "alias$i@test.local"]);
    $m->in_password = 'pw';
    $m->save();
}
echo App\Mailbox::count()." mailboxes\n";
// Helpdesk agents (V>=10 theme: @fwd forwards and agent replies by email). Inserted directly: no subscriptions, so no notification mails are triggered by imports.
// agentN@helpdesk.example, N=1..6; agent6 also owns the alternate address agent6.alt@helpdesk.example. Role admin: may view every conversation.
DB::table('users')->where('email', 'like', 'agent%@helpdesk.example')->delete();
for ($i = 1; $i <= 6; $i++) {
    $u = new App\User();
    $u->forceFill(['first_name' => "Agent", 'last_name' => "No$i", 'email' => "agent$i@helpdesk.example", 'password' => bcrypt('secret'), 'role' => App\User::ROLE_ADMIN,
        'status' => App\User::STATUS_ACTIVE, 'type' => App\User::TYPE_USER, 'emails' => $i == 6 ? 'agent6.alt@helpdesk.example' : null, 'timezone' => 'UTC']);
    $u->save();
}
echo App\User::count()." users\n";
