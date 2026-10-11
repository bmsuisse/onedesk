<?php

namespace App\Misc;

use Symfony\Component\Mailer\Exception\TransportException;
use Symfony\Component\Mailer\Transport\Smtp\EsmtpTransport;

/**
 * SMTP transport for the "TLS" (STARTTLS) encryption setting.
 *
 * SwiftMailer's "tls" mode refused to continue when STARTTLS was not available; Symfony Mailer upgrades opportunistically
 * and would send AUTH credentials and the message in clear text if the STARTTLS offer is stripped by a man in the middle.
 * Everything except the EHLO/STARTTLS handshake is refused until the stream is encrypted.
 */
class RequireTlsEsmtpTransport extends EsmtpTransport
{
    public function executeCommand(string $command, array $codes): string
    {
        if (!preg_match('/^(EHLO|HELO|STARTTLS|QUIT|RSET)\b/i', $command) && !$this->getStream()->isTLS()) {
            throw new TransportException('The SMTP server did not enable TLS (STARTTLS), refusing to send credentials or mail in clear text.');
        }

        return parent::executeCommand($command, $codes);
    }
}
