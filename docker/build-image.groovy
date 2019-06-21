#!/usr/bin/env groovy

pipeline {

  agent {
    kubernetes {
        label "storm-info-provider-docker-build-${env.JOB_BASE_NAME}-${env.BUILD_NUMBER}"
        cloud 'Kube mwdevel'
        inheritFrom 'ci-template'
    }
  }

  options {
    timeout(time: 1, unit: 'HOURS')
    buildDiscarder(logRotator(numToKeepStr: '5'))
  }

  triggers { cron('@daily') }

  environment {
    DOCKER_REGISTRY_HOST = "${env.DOCKER_REGISTRY_HOST}"
    DIRECTORY = "docker"
  }

  parameters {
    booleanParam(defaultValue: false, description: '', name: 'PUSH_TO_REGISTRY')
    booleanParam(defaultValue: true, description: '', name: 'PUSH_TO_DOCKERHUB')
  }

  stages {
    stage('build'){
      steps {
        container('runner'){
          dir("${env.DIRECTORY}") {
            sh "tag=${env.BRANCH_NAME} sh build-image.sh"
          }
        }
      }
    }

    stage('push-registry') {
      when {
        expression {
          return params.PUSH_TO_REGISTRY
        }
      }
      steps {
        container('runner') {
          dir("${env.DIRECTORY}") {
            sh "tag=${env.BRANCH_NAME} sh push-image.sh"
          }
        }
      }
    }

    stage('push-dockerhub') {
      when {
        expression {
          return params.PUSH_TO_DOCKERHUB
        }
      }
      steps {
        container('runner') {
          script {
            withDockerRegistry([ credentialsId: "dockerhub-enrico", url: "" ]) {
              dir("${env.DIRECTORY}") {
                sh "tag=${env.BRANCH_NAME} sh push-image-dockerhub.sh"
              }
            }
          }
        }
      }
    }
  }

  post {
    failure {
      slackSend color: 'danger', message: "${env.JOB_NAME} - #${env.BUILD_NUMBER} Failure (<${env.BUILD_URL}|Open>)"
    }

    changed {
      script{
        if('SUCCESS'.equals(currentBuild.currentResult)) {
          slackSend color: 'good', message: "${env.JOB_NAME} - #${env.BUILD_NUMBER} Back to normal (<${env.BUILD_URL}|Open>)"
        }
      }
    }
  }
}
