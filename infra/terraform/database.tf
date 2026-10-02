resource "random_password" "database" {
  length = 32
  # RDS does not accept '/', '@', '"' or spaces; and the password goes
  # into a URL, so keep to characters that need no escaping there.
  special = false
}

resource "aws_db_subnet_group" "main" {
  name_prefix = "${var.name}-"
  subnet_ids  = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier_prefix = "${var.name}-"
  engine            = "postgres"
  engine_version    = "17"
  instance_class    = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "paritylens"
  username = "paritylens"
  password = random_password.database.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  backup_retention_period    = 7
  auto_minor_version_upgrade = true
  deletion_protection        = !var.allow_destroy
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${var.name}-final"

  # A single instance. Multi-AZ doubles the cost and is the first thing to
  # turn on when this stops being a demo.
  multi_az = false
}
