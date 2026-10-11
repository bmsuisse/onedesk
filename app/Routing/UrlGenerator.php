<?php

namespace App\Routing;

use Illuminate\Routing\UrlGenerator as BaseUrlGenerator;
use Illuminate\Support\Arr;

class UrlGenerator extends BaseUrlGenerator
{
    /**
     * Get the URL to a named route.
     *
     * Passes x_ parameters globally and xs_ parameters only on the same page.
     */
    public function route($name, $parameters = [], $absolute = true)
    {
        if (is_string($name) && ! is_null($this->routes->getByName($name))) {
            $parameters = Arr::wrap($parameters);
            $is_current = ($name == $this->request->route()?->getName());

            foreach ($this->request->query() as $param => $value) {
                if (preg_match('/^x_/', $param) || ($is_current && preg_match('/^xs_/', $param))) {
                    $parameters[$param] = $value;
                }
            }
        }

        return parent::route($name, $parameters, $absolute);
    }

    /**
     * Get the base URL for the request.
     */
    public function formatRoot($scheme, $root = null)
    {
        if (is_null($root)) {
            if (is_null($this->cachedRoot)) {
                // $this->request->root() does not determine subdirectory properly.
                $this->cachedRoot = \Eventy::filter('url_generator.app_url', $this->forcedRoot ?: config('app.url'));

                if (! $this->cachedRoot || \Helper::isDefaultAppUrl($this->cachedRoot)) {
                    $this->cachedRoot = $this->request->root();
                }

                // Remove the slash at the end as on some systems there is a slash at the end.
                $this->cachedRoot = rtrim($this->cachedRoot, '/');
            }

            $root = $this->cachedRoot;
        }

        return parent::formatRoot($scheme, $root);
    }

    /**
     * Format the given URL segments into a single URL.
     */
    public function format($root, $path, $route = null)
    {
        $path = '/'.trim($path, '/');

        // Cut subdirectory from path if the root already contains it.
        $subdirectory = \Helper::getSubdirectory(false, true);
        if ($subdirectory && preg_match('#'.preg_quote($subdirectory, '#').'$#', trim($root, '/'))) {
            $path = preg_replace('#^'.preg_quote($subdirectory, '#').'#', '', $path);
        }

        return parent::format($root, $path, $route);
    }
}
