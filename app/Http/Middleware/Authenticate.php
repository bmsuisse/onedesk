<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Auth\Middleware\Authenticate as Middleware;

class Authenticate extends Middleware
{
    /**
     * Handle an incoming request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  string[]  ...$guards
     */
    public function handle($request, Closure $next, ...$guards)
    {
        \Eventy::action('auth_middleware.handle', $request, $guards, $next);

        return parent::handle($request, $next, ...$guards);
    }
}
