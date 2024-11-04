# psaksh Data Platform — AWS Infrastructure
# Terraform configuration for staging and production environments.
#
# Resources:
#   - S3 data lake (raw / processed / output zones)
#   - RDS MySQL (warehouse)
#   - Lambda functions (pipeline triggers)
#   - IAM roles and policies
#   - CloudWatch log groups

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "psaksh-terraform-state"
    key    = "psaksh-data-platform/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "aws_region"    { default = "us-east-1" }
variable "env"           { default = "staging" }
variable "db_password"   { sensitive = true }
variable "project_name"  { default = "psaksh-data-platform" }

locals {
  name_prefix = "${var.project_name}-${var.env}"
  common_tags = {
    Project     = var.project_name
    Environment = var.env
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# S3 Data Lake
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "data_lake" {
  bucket = "${local.name_prefix}-data-lake"
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle: move processed data to Glacier after 90 days
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "archive-processed"
    status = "Enabled"
    filter { prefix = "processed/" }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# ---------------------------------------------------------------------------
# RDS MySQL (Warehouse)
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "warehouse" {
  name       = "${local.name_prefix}-db-subnet"
  subnet_ids = var.private_subnet_ids
  tags       = local.common_tags
}

resource "aws_db_instance" "warehouse" {
  identifier             = "${local.name_prefix}-warehouse"
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = "db.t3.medium"
  allocated_storage      = 50
  max_allocated_storage  = 200
  storage_encrypted      = true
  db_name                = "psaksh_warehouse"
  username               = "psaksh_admin"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.warehouse.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  backup_retention_period = 7
  deletion_protection    = true
  skip_final_snapshot    = false
  final_snapshot_identifier = "${local.name_prefix}-final-snapshot"
  tags                   = local.common_tags
}

# ---------------------------------------------------------------------------
# IAM Role for ETL Lambda
# ---------------------------------------------------------------------------

resource "aws_iam_role" "etl_lambda" {
  name = "${local.name_prefix}-etl-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "etl_lambda_s3" {
  name = "s3-access"
  role = aws_iam_role.etl_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "s3_bucket_name" {
  value = aws_s3_bucket.data_lake.bucket
}

output "rds_endpoint" {
  value     = aws_db_instance.warehouse.endpoint
  sensitive = true
}
