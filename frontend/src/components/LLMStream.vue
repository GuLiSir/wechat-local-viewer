<template>
  <div class="border-t border-gray-200 bg-white">
    <!-- LLM 交互区域 -->
    <div class="p-3">
      <!-- 流式响应显示 -->
      <div v-if="streaming || responseText || error" class="mb-3 max-h-40 overflow-y-auto">
        <div class="bg-gray-50 rounded-lg p-3">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm font-medium text-gray-700">AI 响应</span>
            <button
              v-if="streaming"
              @click="stopStreaming"
              class="text-xs text-red-500 hover:text-red-600"
            >
              停止
            </button>
          </div>
          <div class="text-sm text-gray-600 whitespace-pre-wrap">
            {{ responseText || progressText || '思考中...' }}
          </div>
          <div v-if="error" class="text-xs text-red-500 mt-2">
            {{ error }}
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="flex items-center space-x-2">
        <input
          v-model="prompt"
          @keydown.enter="sendPrompt"
          type="text"
          placeholder="输入问题，例如：总结最近的聊天内容..."
          class="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          :disabled="streaming"
        />
        <button
          @click="sendPrompt"
          :disabled="streaming || !prompt.trim()"
          class="px-4 py-2 bg-green-500 hover:bg-green-600 disabled:bg-gray-300 text-white rounded-lg text-sm font-medium"
        >
          {{ streaming ? '生成中...' : '总结' }}
        </button>
      </div>

      <div v-if="!hasLLMConfig" class="text-xs text-yellow-600 mt-2">
        ⚠️ 请先在设置中配置 LLM 参数
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { apiClient } from '../api/client'
import { useSessionStore } from '../stores/session'
import { useSettingsStore } from '../stores/settings'
import type { LLMChatRequest } from '../api/types'

const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()

const prompt = ref('')
const responseText = ref('')
const progressText = ref('')
const streaming = ref(false)
const error = ref('')

const hasLLMConfig = computed(() => {
  return !!(settingsStore.llmConfig.base_url &&
            settingsStore.llmConfig.api_key &&
            settingsStore.llmConfig.model)
})

async function sendPrompt() {
  if (!prompt.value.trim() || !sessionStore.currentSession || streaming.value) return
  if (!hasLLMConfig.value) {
    error.value = '请先在「设置」（右上角 ⚙️）中配置 LLM：Base URL / API Key / Model'
    return
  }

  const request: LLMChatRequest = {
    session: sessionStore.currentSession.username,
    prompt: prompt.value.trim(),
    base_url: settingsStore.llmConfig.base_url,
    api_key: settingsStore.llmConfig.api_key,
    model: settingsStore.llmConfig.model,
  }

  streaming.value = true
  error.value = ''
  responseText.value = ''
  progressText.value = ''

  try {
    await apiClient.streamLLM(request, (event) => {
      switch (event.type) {
        case 'start':
          responseText.value = ''
          progressText.value = ''
          break
        case 'progress':
          progressText.value = event.content || ''
          break
        case 'content':
          responseText.value += event.content || ''
          break
        case 'end':
          streaming.value = false
          progressText.value = ''
          if (!responseText.value && !error.value) {
            error.value = '模型没有返回内容（可能思考过程超出 token 预算被截断），请重试'
          }
          break
        case 'error':
          error.value = event.error || '未知错误'
          progressText.value = ''
          streaming.value = false
          break
      }
    })
  } catch (e: any) {
    error.value = String(e?.message || e)
    streaming.value = false
  } finally {
    if (streaming.value) streaming.value = false
  }
}

function stopStreaming() {
  streaming.value = false
  apiClient.abortStream()
}
</script>