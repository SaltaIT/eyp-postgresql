class postgresql::pgbouncer (
                $manage_package         = true,
                $package_ensure         = 'installed',
                $manage_service         = true,
                $manage_docker_service  = true,
                $service_ensure         = 'running',
                $service_enable         = true,
                $auth_type              = 'md5',
                $auth_user              = undef,
                $enable_auth_query      = false,
                $auth_query             = 'SELECT * FROM pgbouncer.get_auth($1)',
                $listen_addr            = '127.0.0.1',
                $listen_port            = '6432',
                $logfile                = '/var/log/pgbouncer/pgbouncer.log',
                $pool_mode              = 'session',
                $realize_dbs_tag        = undef,
                $realize_users_tag      = undef,
                $set_pgbouncer_password = undef,
                $dbhost_pgbouncer       = '127.0.0.1',
                $src_ip_pgbouncer       = '127.0.0.1',
                $verbose                = '0',
                $server_fast_close      = false,
                $max_client_conn        = 200,
                $default_pool_size      = 100,
              ) inherits postgresql::params {

  class { 'postgresql::pgbouncer::install': } ->
  class { 'postgresql::pgbouncer::config': } ~>
  class { 'postgresql::pgbouncer::service': } ->
  Class['postgresql::pgbouncer']

}
