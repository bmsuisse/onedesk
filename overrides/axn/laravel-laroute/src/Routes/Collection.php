<?php

namespace Axn\Laroute\Routes;

use Illuminate\Routing\Route;
use Illuminate\Support\Arr;
use Lord\Laroute\Routes\Collection as BaseCollection;

class Collection extends BaseCollection
{
    /**
     * Get the collection of items as JSON **pretty printed**.
     *
     * @return string
     */
    /**
     * Module alias to generate routes for (FreeScout); null = routes of the main application only.
     */
    public $module = null;

    public function __construct(\Illuminate\Routing\RouteCollectionInterface $routes, $filter, $namespace, $module = null)
    {
        $this->module = $module;

        parent::__construct($routes, $filter, $namespace);
    }

    public function toJson($options = 0)
    {
        $options = JSON_PRETTY_PRINT | $options;

        return json_encode($this->jsonSerialize(), $options);
    }

    /**
     * Get the route information for a given route.
     *
     * @param $route     \Illuminate\Routing\Route
     * @param $filter    string
     * @param $namespace string
     *
     * @return array
     */
    protected function getRouteInformation(Route $route, $filter, $namespace)
    {
        $data = parent::getRouteInformation($route, $filter, $namespace);

        if (!$data || empty($data['name'])) {
            return null;
        }

        // If `module` is set we choose only routes of this module, otherwise only routes outside of modules (FreeScout).
        $action = $route->getAction();

        if ($action && !empty($action['controller'])) {
            preg_match('/^Modules\\\\([^\\\\]+)\\\\/', $action['controller'], $m);

            if (!empty($m[1])) {
                if (!$this->module || $this->module != strtolower($m[1])) {
                    return null;
                }
            } elseif ($this->module) {
                return null;
            }
        }

        return Arr::only($data, ['uri', 'name']);
    }
}
