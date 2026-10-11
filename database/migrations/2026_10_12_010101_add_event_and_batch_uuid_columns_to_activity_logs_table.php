<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

// spatie/laravel-activitylog 4.x columns.
class AddEventAndBatchUuidColumnsToActivityLogsTable extends Migration
{
    public function up()
    {
        Schema::table(config('activitylog.table_name', 'activity_log'), function (Blueprint $table) {
            if (!Schema::hasColumn($table->getTable(), 'event')) {
                $table->string('event')->nullable()->after('subject_type');
            }
            if (!Schema::hasColumn($table->getTable(), 'batch_uuid')) {
                $table->uuid('batch_uuid')->nullable()->after('properties');
            }
        });
    }

    public function down()
    {
        Schema::table(config('activitylog.table_name', 'activity_log'), function (Blueprint $table) {
            $table->dropColumn(['event', 'batch_uuid']);
        });
    }
}
