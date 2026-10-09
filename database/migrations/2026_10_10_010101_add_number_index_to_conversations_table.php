<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

// Conversation::creating runs max('number') on every insert.
class AddNumberIndexToConversationsTable extends Migration
{
    const INDEX = 'conversations_number_index';

    public function up()
    {
        if ($this->hasIndex()) {
            return;
        }
        // ponytail: non-unique on purpose, existing data may contain duplicates.
        Schema::table('conversations', function (Blueprint $table) {
            $table->index('number', self::INDEX);
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
        $indexes = Schema::getConnection()->getDoctrineSchemaManager()
            ->listTableIndexes(Schema::getConnection()->getTablePrefix().'conversations');

        return array_key_exists(self::INDEX, $indexes);
    }
}
