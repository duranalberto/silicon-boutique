{{- define "silicon-boutique-monitoring.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "silicon-boutique-monitoring.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "silicon-boutique-monitoring.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "silicon-boutique-monitoring.labels" -}}
helm.sh/chart: {{ include "silicon-boutique-monitoring.chart" . }}
app.kubernetes.io/name: {{ include "silicon-boutique-monitoring.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: silicon-boutique
silicon-boutique/component: monitoring
silicon-boutique/run-id: {{ .Values.siliconBoutique.runId | quote }}
silicon-boutique/environment: {{ .Values.siliconBoutique.environment | quote }}
silicon-boutique/machine-type: {{ .Values.siliconBoutique.machineType | quote }}
silicon-boutique/processor-family: {{ .Values.siliconBoutique.processorFamily | quote }}
silicon-boutique/architecture: {{ .Values.siliconBoutique.architecture | quote }}
{{- end -}}

{{- define "silicon-boutique-monitoring.frontendUrl" -}}
{{- $path := .Values.siliconBoutique.frontendPath | default "/" -}}
{{- if hasPrefix "/" $path -}}
{{- printf "http://%s.%s.svc.cluster.local%s" .Values.siliconBoutique.frontendServiceName .Values.siliconBoutique.workloadNamespace $path -}}
{{- else -}}
{{- printf "http://%s.%s.svc.cluster.local/%s" .Values.siliconBoutique.frontendServiceName .Values.siliconBoutique.workloadNamespace $path -}}
{{- end -}}
{{- end -}}
