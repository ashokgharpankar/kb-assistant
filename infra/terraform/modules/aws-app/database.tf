# ---------------------------------------------------------------------------
# Aurora PostgreSQL Serverless v2 with pgvector, scaling to zero (ADR 0024).
# Same schema and SQL as local Postgres: hybrid search needs both pgvector and
# full-text search in one database.
# ---------------------------------------------------------------------------

data "aws_rds_engine_version" "postgres" {
  engine  = "aurora-postgresql"
  version = var.aurora_postgres_major
  latest  = true
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_rds_cluster" "main" {
  #checkov:skip=CKV2_AWS_27:Statement logging (log_statement) writes every query, including user questions, to CloudWatch: cost and privacy. Errors are exported (postgresql log).
  #checkov:skip=CKV_AWS_139:Dev database: deletion protection off so terraform destroy works. On for production.
  #checkov:skip=CKV2_AWS_8:Dev: Aurora's automated backups (1 day) are enough; no AWS Backup plan.
  #checkov:skip=CKV_AWS_327:Encrypted with the AWS-managed RDS key; a customer-managed KMS key adds $1/month and nothing for public-source data.
  cluster_identifier = var.name
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"                                       # Serverless v2 runs on the provisioned engine mode
  engine_version     = data.aws_rds_engine_version.postgres.version_actual # e.g. 16.8, the latest 16.x
  database_name      = "kb"
  master_username    = "kb_admin"

  # RDS creates and rotates the password in Secrets Manager. It never appears in
  # Terraform, its state, or a tfvars file.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]

  serverlessv2_scaling_configuration {
    min_capacity             = 0 # pause when idle: storage cost only
    max_capacity             = var.aurora_max_acu
    seconds_until_auto_pause = var.aurora_pause_after_seconds
  }

  storage_encrypted                   = true
  iam_database_authentication_enabled = true
  backup_retention_period             = 1
  copy_tags_to_snapshot               = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]

  # Dev: destroy without a final snapshot. Production: false, with deletion_protection.
  skip_final_snapshot = true
  deletion_protection = false
}

resource "aws_rds_cluster_instance" "main" {
  #checkov:skip=CKV_AWS_118:Enhanced monitoring costs extra and needs a role; CloudWatch metrics are enough in dev.
  #checkov:skip=CKV_AWS_353:Performance Insights is not needed for a dev database.
  identifier                 = "${var.name}-1"
  cluster_identifier         = aws_rds_cluster.main.id
  instance_class             = "db.serverless"
  engine                     = aws_rds_cluster.main.engine
  engine_version             = aws_rds_cluster.main.engine_version
  db_subnet_group_name       = aws_db_subnet_group.main.name
  publicly_accessible        = false
  auto_minor_version_upgrade = true
}
