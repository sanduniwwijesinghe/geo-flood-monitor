{{- define "gfm.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "gfm.labels" -}}
app.kubernetes.io/part-of: geo-flood-monitor
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "gfm.titiler.selector" -}}
app.kubernetes.io/name: titiler
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "gfm.titiler.name" -}}
{{ include "gfm.fullname" . }}-titiler
{{- end -}}
