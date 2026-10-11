<?php

namespace App\Providers;

use Illuminate\Support\Facades\Schema;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Bootstrap any application services.
     *
     * @return void
     */
    public function boot()
    {
        // To avoid MySQL error in packages:
        // "SQLSTATE[42000]: Syntax error or access violation: 1071 Specified key was too long; max key length is 767 bytes"
        Schema::defaultStringLength(191);

        \Illuminate\Support\Facades\Date::use(\App\Support\Carbon::class);

        // Behind a TLS-terminating proxy which is not trusted Request::isSecure()
        // does not follow APP_URL, so make the request secure if APP_URL is https.
        if (!$this->app->runningInConsole() && \Helper::isHttps()) {
            $this->app['request']->server->set('HTTPS', 'on');
        }

        // Models observers
        \App\Mailbox::observe(\App\Observers\MailboxObserver::class);
        // Eloquent events for this table are not called automatically, so need to be called manually.
        //\App\MailboxUser::observe(\App\Observers\MailboxUserObserver::class);
        \App\Email::observe(\App\Observers\EmailObserver::class);
        \App\User::observe(\App\Observers\UserObserver::class);
        \App\Conversation::observe(\App\Observers\ConversationObserver::class);
        \App\Customer::observe(\App\Observers\CustomerObserver::class);
        \App\Thread::observe(\App\Observers\ThreadObserver::class);
        \App\Attachment::observe(\App\Observers\AttachmentObserver::class);
        \App\Follower::observe(\App\Observers\FollowerObserver::class);
        \Illuminate\Notifications\DatabaseNotification::observe(\App\Observers\DatabaseNotificationObserver::class);

        \Validator::extend('safehost', function ($attribute, $value, $parameters, $validator) {
            if (!$value) {
                return true;
            }
            $msg = '';
            try {
                $url = $value;
                if (!preg_match("#^https?://#", $value)) {
                    $url = 'https://'.$url;
                }
                \Helper::sanitizeRemoteUrl($url, true);
            } catch (\Exception $e) {
                $msg = $e->getMessage();
            }
            if ($msg) {
                $validator->errors()->add($attribute, $msg);
                return false;
            }

            return true;
        });
    }

    /**
     * Register any application services.
     *
     * @return void
     */
    public function register()
    {
        // URL generator with x_/xs_ params propagation, app_url filter and subdirectory handling.
        // The extend() callbacks of the framework's RoutingServiceProvider still apply.
        $this->app->singleton('url', function ($app) {
            $routes = $app['router']->getRoutes();
            $app->instance('routes', $routes);

            return new \App\Routing\UrlGenerator(
                $routes,
                $app->rebinding('request', function ($app, $request) {
                    $app['url']->setRequest($request);
                }),
                $app['config']['app.asset_url']
            );
        });

        // Ignore imap "Unexpected characters at end of address" warnings.
        $previous_handler = null;
        $previous_handler = set_error_handler(function ($level, $message, $file = '', $line = 0) use (&$previous_handler) {
            if (strstr($message, 'Unexpected characters at end of address')) {
                return true;
            }

            return $previous_handler ? call_user_func($previous_handler, $level, $message, $file, $line) : false;
        });

        // Forse HTTPS if using CloudFlare "Flexible SSL"
        // https://support.cloudflare.com/hc/en-us/articles/200170416-What-do-the-SSL-options-mean-
        if (\Helper::isHttps()) {
            // $_SERVER['HTTPS'] = 'on';
            // $_SERVER['SERVER_PORT'] = '443';
            $this->app['url']->forceScheme('https');
        }

        // If APP_KEY is not set, redirect to /install.php
        if (!\Config::get('app.key') && !app()->runningInConsole() && !file_exists(storage_path('.installed'))) {
            // Not defined here yet
            //\Artisan::call("freescout:clear-cache");
            redirect(\Helper::getSubdirectory().'/install.php')->send();
        }

        // Process module registration error - disable module and show error to admin
        \Eventy::addFilter('modules.register_error', function ($exception, $module) {

            $msg = __('The :module_name module has been deactivated due to an error: :error_message', ['module_name' => $module->getName(), 'error_message' => $exception->getMessage()]);

            \Log::error($msg);

            // request() does is empty at this stage
            if (!empty($_POST['action']) && $_POST['action'] == 'activate') {

                // During module activation in case of any error we have to deactivate module.
                \App\Module::deactiveModule($module->getAlias());

                \Session::flash('flashes_floating', [[
                    'text' => $msg,
                    'type' => 'danger',
                    'role' => \App\User::ROLE_ADMIN,
                ]]);

                return;
            } elseif (empty($_POST)) {

                // failed to open stream: No such file or directory
                if (strstr($exception->getMessage(), 'No such file or directory')) {
                    \App\Module::deactiveModule($module->getAlias());

                    \Session::flash('flashes_floating', [[
                        'text' => $msg,
                        'type' => 'danger',
                        'role' => \App\User::ROLE_ADMIN,
                    ]]);
                }

                return;
            }

            return $exception;
        }, 10, 2);
    }
}
