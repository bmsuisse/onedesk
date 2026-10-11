<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

// Folder::preloadWaitingSince groups by folder_id and aggregates last_reply_at per folder.
class AddFolderStateStatusLastReplyIndexToConversationsTable extends Migration
{
    const INDEX = 'conversations_folder_state_status_last_reply_index';

    public function up()
    {
        if ($this->hasIndex()) {
            return;
        }
        Schema::table('conversations', function (Blueprint $table) {
            $table->index(['folder_id', 'state', 'status', 'last_reply_at'], self::INDEX);
        });
    }

    public function down()
    {
        if (!$this->hasIndex()) {
            return;
        }
        Schema::table('conversations', function (Blueprint $table) {
            $table->dropIndex(self::INDEX);
        });
    }

    private function hasIndex()
    {
        return Schema::hasIndex('conversations', self::INDEX);
    }
}
