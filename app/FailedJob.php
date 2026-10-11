<?php

namespace App;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\Artisan;

class FailedJob extends Model
{
    /**
     * Automatically converted into Carbon dates.
     */
    protected $dates = ['failed_at'];

	public $payload_decoded = null;

    public function getPayloadDecoded()
    {
    	if ($this->payload_decoded !== null) {
    		return $this->payload_decoded;
    	}

    	$this->payload_decoded = json_decode((string) $this->payload, true);

    	return $this->payload_decoded;
    }

    public function getCommand()
    {
    	return \App\Job::getPayloadCommand($this->getPayloadDecoded());
    }

    public static function retry($job_id)
    {
        Artisan::call('queue:retry', ['id' => $job_id]);
    }
}
