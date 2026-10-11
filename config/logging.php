<?php

use Monolog\Handler\StreamHandler;

return [
    // Laravel 5.5 used app.log ('single' | 'daily' | 'syslog' | 'errorlog'); logs for 5 days are kept by default.
    'default' => env('LOG_CHANNEL', env('APP_LOG', 'daily')),

    'channels' => [
        'single' => [
            'driver' => 'single',
            'path' => storage_path('logs/laravel.log'),
            'level' => 'debug',
        ],
        'daily' => [
            'driver' => 'daily',
            'path' => storage_path('logs/laravel.log'),
            'level' => 'debug',
            'days' => (int) env('APP_LOG_MAX_FILES', 5),
        ],
        'syslog' => [
            'driver' => 'syslog',
            'level' => 'debug',
        ],
        'errorlog' => [
            'driver' => 'errorlog',
            'level' => 'debug',
        ],
        'emergency' => [
            'path' => storage_path('logs/laravel.log'),
        ],
    ],
];
