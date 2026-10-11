<?php

namespace App\Auth;

use Illuminate\Auth\SessionGuard;

class FreeScoutSessionGuard extends SessionGuard
{
    /**
     * Determine if the user matches the credentials.
     * Same as the parent, but modules can veto or extend the check (LDAP, SSO, 2FA).
     *
     * @param  mixed  $user
     * @param  array  $credentials
     * @return bool
     */
    protected function hasValidCredentials($user, $credentials)
    {
        $validated = ! is_null($user) && \Eventy::filter(
            'session_guard.validate_credentials',
            $this->provider->validateCredentials($user, $credentials),
            $user,
            $credentials
        );

        if ($validated) {
            $this->fireValidatedEvent($user);
        }

        return $validated;
    }
}
