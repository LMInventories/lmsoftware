import { create } from 'zustand'
import { getLocalInspections, getLocalInspection, updateReportData } from '../services/database'
import type { HumanRecording } from '../components/HumanTypistRecorder'

interface InspectionStore {
  inspections: any[]
  activeInspection: any | null
  // Human typist recordings keyed by inspectionId — persists across screen navigation
  humanRecordings: Record<number, HumanRecording[]>
  loadInspections: () => Promise<void>
  loadInspection: (id: number) => Promise<void>
  setReportData: (inspectionId: number, reportData: any) => Promise<void>
  updateSectionInReport: (inspectionId: number, sectionKey: string, sectionData: any) => Promise<void>
  updateItemInReport: (inspectionId: number, sectionKey: string, itemKey: string, itemData: any) => Promise<void>
  addHumanRecording: (inspectionId: number, rec: HumanRecording) => void
  removeHumanRecording: (inspectionId: number, recId: string) => void
}

export const useInspectionStore = create<InspectionStore>((set, get) => ({
  inspections: [],
  activeInspection: null,
  humanRecordings: {},

  loadInspections: async () => {
    const inspections = await getLocalInspections()
    set({ inspections })
  },

  loadInspection: async (id) => {
    const inspection = await getLocalInspection(id)
    set({ activeInspection: inspection })
  },

  setReportData: async (inspectionId, reportData) => {
    const json = typeof reportData === 'string' ? reportData : JSON.stringify(reportData)
    await updateReportData(inspectionId, json)
    const { activeInspection } = get()
    if (activeInspection?.id === inspectionId) {
      set({ activeInspection: { ...activeInspection, report_data: json } })
    }
    const inspections = await getLocalInspections()
    set({ inspections })
  },

  updateSectionInReport: async (inspectionId, sectionKey, sectionData) => {
    const inspection = await getLocalInspection(inspectionId)
    if (!inspection) return
    const reportData = inspection.report_data ? JSON.parse(inspection.report_data) : {}
    reportData[sectionKey] = sectionData
    await get().setReportData(inspectionId, reportData)
  },

  updateItemInReport: async (inspectionId, sectionKey, itemKey, itemData) => {
    const inspection = await getLocalInspection(inspectionId)
    if (!inspection) return
    const reportData = inspection.report_data ? JSON.parse(inspection.report_data) : {}
    if (!reportData[sectionKey]) reportData[sectionKey] = {}
    if (!reportData[sectionKey].items) reportData[sectionKey].items = {}
    reportData[sectionKey].items[itemKey] = {
      ...(reportData[sectionKey]?.items?.[itemKey] || {}),
      ...itemData,
    }
    await get().setReportData(inspectionId, reportData)
  },

  addHumanRecording: (inspectionId, rec) => {
    const { humanRecordings } = get()
    const existing = humanRecordings[inspectionId] || []
    set({ humanRecordings: { ...humanRecordings, [inspectionId]: [...existing, rec] } })
  },

  removeHumanRecording: (inspectionId, recId) => {
    const { humanRecordings } = get()
    const existing = humanRecordings[inspectionId] || []
    set({ humanRecordings: { ...humanRecordings, [inspectionId]: existing.filter(r => r.id !== recId) } })
  },
}))
