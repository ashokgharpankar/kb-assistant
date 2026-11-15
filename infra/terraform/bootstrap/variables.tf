variable "project" {
  description = "Project name, used in resource names and the Project tag."
  type        = string
  default     = "kb-assistant"
}

variable "owner" {
  description = "Value for the Owner tag."
  type        = string
  default     = "ashok"
}

variable "region" {
  description = "AWS region. us-east-1 has the widest Bedrock model coverage."
  type        = string
  default     = "us-east-1"
}
