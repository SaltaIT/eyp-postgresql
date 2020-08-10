class postgresql::params {

  $version_default='11'

  $port_default='5432'
  $log_directory_default='pg_log'
  $log_filename_default='postgresql-%Y%m%d.log'
  $timezone_default='Europe/Andorra'

  $pgbouncer_service_name = 'pgbouncer'
  $pgbouncer_package_name = 'pgbouncer'

  $pidfile = {
                    '9.2' => '/var/lock/subsys/postgresql-9.2',
                    '9.6' => undef,
                    '10' => undef,
                    '11' => undef,
                    '12' => undef,
                  }

  $postgis = {
              '23_10' => 'postgis23_10',
              '24_10' => 'postgis24_10',
              '25_10' => 'postgis25_10',
              '23_11' => 'postgis23_11',
              '24_11' => 'postgis24_11',
              '25_11' => 'postgis25_11',
            }

  $contrib = {
              '9.2' => 'postgresql92-contrib',
              '9.6' => 'postgresql96-contrib',
              '10' => 'postgresql10-contrib',
              '11' => 'postgresql11-contrib',
              '12' => 'postgresql12-contrib',
            }

  case $facts['os']['family']
  {
    'redhat':
    {
      $repoprovider = 'rpm'
      $fix_systemd_pg_ctlcluster = false
      $sysconfig=true

      $postgresuser='postgres'
      $postgresgroup='postgres'
      $postgreshome='/var/lib/pgsql'

      $reposource =  {
                      '9.6' => 'https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm',
                      '10'  => 'https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm',
                      '11'  => 'https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm',
                      '12'  => 'https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm',
                      }
      $reponame = {
                    '9.6' => 'pgdg-redhat-repo',
                    '10'  => 'pgdg-redhat-repo',
                    '11'  => 'pgdg-redhat-repo',
                    '12'  => 'pgdg-redhat-repo',
                  }

      $packagename= {
                      '9.2' => [ 'postgresql92-server' ],
                      '9.6' => [ 'postgresql96-server' ],
                      '10'  => [ 'postgresql10-server' ],
                      '11'  => [ 'postgresql11-server' ],
                      '12'  => [ 'postgresql12-server' ],
                    }

      $packagename_client = {
                              '9.2' => [ 'postgresql92' ],
                              '9.6' => [ 'postgresql96' ],
                              '10'  => [ 'postgresql10' ],
                              '11'  => [ 'postgresql11' ],
                              '12'  => [ 'postgresql12' ],
                            }

      $datadir_default = {
                            '9.2' => '/var/lib/pgsql/9.2/data',
                            '9.6' => '/var/lib/pgsql/9.6/data',
                            '10'  => '/var/lib/pgsql/10/data',
                            '11'  => '/var/lib/pgsql/11/data',
                            '12'  => '/var/lib/pgsql/12/data',
                        }

      $initdb = {
                  '9.2' => '/usr/pgsql-9.2/bin/initdb',
                  '9.6' => '/usr/pgsql-9.6/bin/initdb',
                  '10'  => '/usr/pgsql-10/bin/initdb',
                  '11'  => '/usr/pgsql-11/bin/initdb',
                  '12'  => '/usr/pgsql-12/bin/initdb',
                }

      $servicename = {
                        '9.2' => 'postgresql-9.2',
                        '9.6' => 'postgresql-9.6',
                        '10' => 'postgresql-10',
                        '11' => 'postgresql-11',
                        '12' => 'postgresql-12',
                      }

      case $facts['os']['release']['full']
      {
        /^6.*$/:
        {
          $systemd=false
        }
        /^[78].*$/:
        {
          $systemd=true
        }
        default: { fail("Unsupported version! - ${::operatingsystemrelease}")  }
      }
    }
    'Debian':
    {
      $sysconfig=false

      $postgresuser='postgres'
      $postgresgroup='postgres'
      $postgreshome='/var/lib/postgresql'

      $fix_systemd_pg_ctlcluster = true

      $initdb = {
                  '9.2' => '/usr/lib/postgresql/9.2/bin/initdb',
                  '9.6' => '/usr/lib/postgresql/9.6/bin/initdb',
                  '10'  => '/usr/lib/postgresql/10/bin/initdb',
                  '11'  => '/usr/lib/postgresql/11/bin/initdb',
                  '12'  => '/usr/lib/postgresql/12/bin/initdb',
                }

      $datadir_default = {
                            '9.2' => '/var/lib/postgresql/9.2/main',
                            '9.6' => '/var/lib/postgresql/9.6/main',
                            '10' => '/var/lib/postgresql/10/main',
                            '11' => '/var/lib/postgresql/11/main',
                            '12' => '/var/lib/postgresql/12/main',
                        }

      $packagename= {
                      '9.2' => [ 'postgresql-9.2' ],
                      '9.6' => [ 'postgresql-9.6' ],
                      '10'  => [ 'postgresql-10' ],
                      '11'  => [ 'postgresql-11' ],
                      '12'  => [ 'postgresql-12' ],
                    }

      $packagename_client = {
                              '9.2' => [ 'postgresql-client-9.2' ],
                              '9.6' => [ 'postgresql-client-9.6' ],
                              '10'  => [ 'postgresql-client-19' ],
                              '11'  => [ 'postgresql-client-11' ],
                              '12'  => [ 'postgresql-client-12' ],
                            }

      $servicename = {
                        '9.2' => 'postgresql@9.2-main.service',
                        '9.6' => 'postgresql@9.6-main.service',
                        '10'  => 'postgresql@10-main.service',
                        '11'  => 'postgresql@11-main.service',
                        '12'  => 'postgresql@12-main.service',
                      }

      case $::architecture
      {
        'armv7l':
        {
          #raspberry
          $repoprovider = 'raspbian10'

          case $facts['os']['name']
          {
            'Debian':
            {
              case $facts['os']['release']['full']
              {
                /^10.*$/:
                {
                  $systemd=true
                }
                default: { fail("Unsupported Debian version! - ${::operatingsystemrelease}")  }
              }
            }
            default: { fail('Unsupported Debian flavour!')  }
          }
        }
        default:
        {
          $repoprovider = 'apt'

          case $facts['os']['name']
          {
            'Ubuntu':
            {
              case $facts['os']['release']['full']
              {
                /^14.*$/:
                {
                  $systemd=false
                }
                /^1[68].*$/:
                {
                  $systemd=true
                }
                /^20.*$/:
                {
                  $systemd=true
                }
                default: { fail("Unsupported Ubuntu version! - ${::operatingsystemrelease}")  }
              }
            }
            'Debian':
            {
              case $facts['os']['release']['full']
              {
                /^8.*$/:
                {
                  $systemd=false
                }
                /^9.*$/:
                {
                  $systemd=true
                }
                /^10.*$/:
                {
                  $systemd=true
                }
                default: { fail("Unsupported Debian version! - ${::operatingsystemrelease}")  }
              }
            }
            default: { fail('Unsupported Debian flavour!')  }
          }
        }
      }
    }
    default: { fail('Unsupported OS!')  }
  }
}
