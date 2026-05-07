{{- define "silicon-boutique-online-boutique.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "silicon-boutique-online-boutique.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "silicon-boutique-online-boutique.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "silicon-boutique-online-boutique.labelsJson" -}}
{{- dict
  "app.kubernetes.io/part-of" "silicon-boutique"
  "silicon-boutique/run-id" .Values.siliconBoutique.runId
  "silicon-boutique/environment" .Values.siliconBoutique.environment
  "silicon-boutique/machine-type" .Values.siliconBoutique.machineType
  "silicon-boutique/processor-family" .Values.siliconBoutique.processorFamily
  "silicon-boutique/architecture" (.Values.siliconBoutique.architecture | replace "_" "-")
  | toJson -}}
{{- end -}}

{{- define "silicon-boutique-online-boutique.annotationsJson" -}}
{{- dict
  "silicon-boutique/teardown-owner" "helm"
  "silicon-boutique/teardown-scope" "workload"
  "silicon-boutique/teardown-rule" "uninstall-before-terraform-destroy"
  | toJson -}}
{{- end -}}

{{- define "silicon-boutique-online-boutique.loadGeneratorJson" -}}
{{- dict
  "CONCURRENT_USERS" (toString .Values.siliconBoutique.loadGenerator.concurrentUsers)
  "USERS_PER_SECOND" (toString .Values.siliconBoutique.loadGenerator.usersPerSecond)
  "TEST_DURATION" .Values.siliconBoutique.loadGenerator.testDuration
  "USERS" (toString .Values.siliconBoutique.loadGenerator.concurrentUsers)
  "RATE" (toString .Values.siliconBoutique.loadGenerator.usersPerSecond)
  "LOCUST_RUN_TIME" .Values.siliconBoutique.loadGenerator.testDuration
  | toJson -}}
{{- end -}}
