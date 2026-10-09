<?php
// Creates N IMAP mailboxes (mb1..mbN@test.local) pointing at the mock Dovecot. Usage: php seed.php N
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
App\Mailbox::query()->delete();
for ($i = 1; $i <= (int) $argv[1]; $i++) {
    $m = new App\Mailbox();
    $m->forceFill(['name' => "MB$i", 'email' => "mb$i@test.local", 'in_server' => getenv('E2E_IMAP_HOST'), 'in_port' => 143,
        'in_username' => "mb$i@test.local", 'in_protocol' => 1, 'in_encryption' => 1, 'in_validate_cert' => 0, 'out_method' => 1]);
    $m->in_password = 'pw';
    $m->save();
}
echo App\Mailbox::count()." mailboxes\n";
