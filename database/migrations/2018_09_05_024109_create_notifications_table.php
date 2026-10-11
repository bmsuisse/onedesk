<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

class CreateNotificationsTable extends Migration
{
    /**
     * Run the migrations.
     *
     * @return void
     */
    public function up()
    {
        \Helper::disableSqlRequirePrimaryKey();
        
        Schema::create('notifications', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('type');
            // Laravel 5.5 morphs(): unsigned INT id + string type, index (id, type). Laravel 6+ changed the type and index order.
            $table->unsignedInteger('notifiable_id');
            $table->string('notifiable_type');
            $table->index(['notifiable_id', 'notifiable_type']);
            $table->text('data');
            $table->timestamp('read_at')->nullable();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     *
     * @return void
     */
    public function down()
    {
        Schema::dropIfExists('notifications');
    }
}
