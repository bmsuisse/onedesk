<?php

namespace App\Http\Middleware;

use App\Misc\Helper;
use Closure;
use Symfony\Component\HttpFoundation\IpUtils;
use Symfony\Component\HttpFoundation\Request as SymfonyRequest;

/**
 * Use CF-Connecting-IP as the client IP (GHSA-9cm3-qvj2-8hg4).
 * The header is honoured only if the request comes from Cloudflare or a trusted proxy,
 * otherwise anybody could spoof it.
 */
class CloudflareRealIp
{
    /**
     * https://www.cloudflare.com/ips/
     */
    public static $cloudflare_ranges = [
        '173.245.48.0/20',
        '103.21.244.0/22',
        '103.22.200.0/22',
        '103.31.4.0/22',
        '141.101.64.0/18',
        '108.162.192.0/18',
        '190.93.240.0/20',
        '188.114.96.0/20',
        '197.234.240.0/22',
        '198.41.128.0/17',
        '162.158.0.0/15',
        '104.16.0.0/13',
        '104.24.0.0/14',
        '172.64.0.0/13',
        '131.0.72.0/22',
        '2400:cb00::/32',
        '2606:4700::/32',
        '2803:f800::/32',
        '2405:b500::/32',
        '2405:8100::/32',
        '2a06:98c0::/29',
        '2c0f:f248::/32',
    ];

    public function handle($request, Closure $next)
    {
        if (config('app.cloudflare_is_used')) {
            $remote_addr = $request->server->get('REMOTE_ADDR');
            $cf_ip = $request->server->get('HTTP_CF_CONNECTING_IP');

            if ($remote_addr && $cf_ip && $cf_ip !== $remote_addr
                && Helper::isValidIp($cf_ip)
                && self::isTrustedSource($remote_addr)
            ) {
                $request->server->set('REMOTE_ADDR', $cf_ip);
                $_SERVER['REMOTE_ADDR'] = $cf_ip;
            }
        }

        return $next($request);
    }

    public static function isTrustedSource($remote_addr)
    {
        $trusted = array_merge(self::$cloudflare_ranges, SymfonyRequest::getTrustedProxies());

        return IpUtils::checkIp($remote_addr, $trusted);
    }
}
