<?php

namespace App\Providers;

use App\Auth\FreeScoutSessionGuard;
use Illuminate\Support\ServiceProvider;

class FreeScoutAuthServiceProvider extends ServiceProvider
{
    /**
     * Replace the "session" guard driver with one that fires FreeScout hooks.
     */
    public function boot()
    {
        $this->app['auth']->extend('session', function ($app, $name, array $config) {
            $guard = new FreeScoutSessionGuard(
                $name,
                $app['auth']->createUserProvider($config['provider'] ?? null),
                $app['session.store'],
                rehashOnLogin: $app['config']->get('hashing.rehash_on_login', true),
                timeboxDuration: $app['config']->get('auth.timebox_duration', 200000),
            );

            $guard->setCookieJar($app['cookie']);
            $guard->setDispatcher($app['events']);
            $guard->setRequest($app->refresh('request', $guard, 'setRequest'));

            if (isset($config['remember'])) {
                $guard->setRememberDuration($config['remember']);
            }

            return $guard;
        });
    }
}
