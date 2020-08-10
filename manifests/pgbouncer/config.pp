class postgresql::pgbouncer::config inherits postgresql::pgbouncer {

  concat { '/etc/pgbouncer/pgbouncer.ini':
    ensure => 'present',
    owner  => 'root',
    group  => 'root',
    mode   => '0644',
  }

  concat::fragment{ 'base pgbouncer':
    order   => '00',
    target  => '/etc/pgbouncer/pgbouncer.ini',
    content => template("${module_name}/pgbouncer/pgbouncer.erb"),
  }

  concat { '/etc/pgbouncer/pgbouncer-databases.ini':
    ensure => 'present',
    owner  => 'root',
    group  => 'root',
    mode   => '0644',
  }

  concat::fragment{ 'base pgbouncer databases':
    order   => '00',
    target  => '/etc/pgbouncer/pgbouncer-databases.ini',
    content => template("${module_name}/pgbouncer/databases-header.erb"),
  }

  concat { '/etc/pgbouncer/userlist.txt':
    ensure => 'present',
    owner  => 'root',
    group  => 'root',
    mode   => '0644',
  }

  if($postgresql::pgbouncer::realize_dbs_tag!=undef)
  {
    Postgresql::Pgbouncer::Database <| tag == $postgresql::pgbouncer::realize_dbs_tag |>
  }

  if($postgresql::pgbouncer::realize_users_tag!=undef)
  {
    Postgresql::Pgbouncer::Username <| tag == $postgresql::pgbouncer::realize_dbs_tag |>
  }

  if($postgresql::pgbouncer::set_pgbouncer_password!=undef)
  {
    postgresql::role { 'pgbouncer':
      password => $postgresql::pgbouncer::set_pgbouncer_password,
      db_host  => $postgresql::pgbouncer::dbhost_pgbouncer,
    }

    $password_hash_md5=md5("${postgresql::pgbouncer::set_pgbouncer_password}pgbouncer")
    $password_hash_sql="md5${password_hash_md5}"

    postgresql::pgbouncer::username { 'pgbouncer':
      password_md5 => $password_hash_sql,
    }

    postgresql::hba_rule { 'pgbouncer':
      user     => 'pgbouncer',
      database => 'all',
      address  => "${postgresql::pgbouncer::src_ip_pgbouncer}/32",
    }

    #user_authentication-sql.erb
    file { '/etc/pgbouncer/.user_authentication.sql':
      ensure  => 'present',
      owner   => 'root',
      group   => 'root',
      mode    => '0644',
      content => template("${module_name}/pgbouncer/user_authentication-sql.erb"),
    }
  }
}
