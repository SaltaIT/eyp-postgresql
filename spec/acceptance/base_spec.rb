require 'spec_helper_acceptance'
require_relative './version.rb'

describe 'postgresql class' do

  context 'basic setup' do
    # Using puppet_apply as a helper
    it 'should work with no errors' do
      pp = <<-EOF

      class { 'postgresql':
    		wal_level => 'hot_standby',
    		max_wal_senders => '3',
    		checkpoint_segments => '8',
    		wal_keep_segments => '8',
    	}

    	postgresql::hba_rule { 'test':
    		user => 'replicator',
    		database => 'replication',
    		address => '192.168.56.0/24',
    	}

    	postgresql::role { 'replicator':
    		replication => true,
    		password => 'replicatorpassword',
    	}

    	postgresql::schema { 'jordi':
    		owner => 'replicator',
    	}

      EOF

      # Run it twice and test for idempotency
      expect(apply_manifest(pp).exit_code).to_not eq(1)
      expect(apply_manifest(pp).exit_code).to eq(0)
    end

    describe package($packagename92) do
      it { is_expected.to be_installed }
    end

    describe service($servicename92) do
      it { should be_enabled }
      it { is_expected.to be_running }
    end

    describe port(5432) do
      it { should be_listening }
    end

    describe file($postgresconf92) do
      it { should be_file }
      its(:content) { should match 'wal_level = hot_standby' }
      its(:content) { should match 'puppet managed file' }
    end

    describe file($pghba92) do
      it { should be_file }
      its(:content) { should match '# rule: test' }
      its(:content) { should match 'host	replication	replicator	192.168.56.0/24			md5' }
      its(:content) { should match 'puppet managed file' }
    end

  end
end
