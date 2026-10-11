<?php

namespace App\Support;

use Illuminate\Support\Carbon as BaseCarbon;

class Carbon extends BaseCarbon
{
    /**
     * Fix for PostgreSQL timestamp fields (timezone suffix, microseconds).
     * https://github.com/freescout-helpdesk/freescout/issues/3702
     */
    public static function createFromFormat($format, $time, $timezone = null): ?static
    {
        if ($format == 'Y-m-d H:i:s' && is_string($time)) {
            $time = preg_replace('/\+.*/', '', $time);

            if (strlen($time) > 19) {
                $time = substr($time, 0, 19);
            }
        }

        return parent::createFromFormat($format, $time, $timezone);
    }
}
