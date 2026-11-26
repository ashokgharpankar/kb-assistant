{{/* Common labels for every object in the release. */}}
{{- define "kb.labels" -}}
app.kubernetes.io/part-of: kb-assistant
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector labels for one component: pass (dict "ctx" $ "component" "api"). */}}
{{- define "kb.selector" -}}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Container hardening shared by every container (Pod Security "restricted"). */}}
{{- define "kb.containerSecurity" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
{{- end -}}
