{{/*
Chart 이름
*/}}
{{- define "findart-collector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
릴리스 전체 이름
*/}}
{{- define "findart-collector.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "findart-collector.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
공통 라벨
*/}}
{{- define "findart-collector.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "findart-collector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Pod selector 라벨
*/}}
{{- define "findart-collector.selectorLabels" -}}
app.kubernetes.io/name: {{ include "findart-collector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* 수집기 CronJob 이름 */}}
{{- define "findart-collector.collectorFullname" -}}
{{- printf "%s-%s" (include "findart-collector.fullname" .root) (.name | kebabcase) | trunc 63 | trimSuffix "-" }}
{{- end }}
