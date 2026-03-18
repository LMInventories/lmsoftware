import { create } from 'zustand'
import { getLocalInspections, getLocalInspection, updateReportData } from '../services/database'

interface InspectionStore {
  inspections: any[]
  activeInspection: any | null
  loadInspections: () => Promise<void>
  loadInspection: (id: number) => Promise<void>
  setReportData: (inspectionId: number, reportData: any) => Promise<void>
  updateSectionInReport: (inspectionId: number, sectionKey: string, sectionData: any) => Promise<void>
  updateItemInReport: (inspectionId: number, sectionKey: string, itemKey: string, itemData: any) => Promise<void>
}

export const useInspectionStore = create<InspectionStore>((set, get) => ({
  inspections: [],
  activeInspection: null,

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
    // Refresh list
    const inspections = await getLocalInspections()
    set({ inspections })
  },

  updateSectionInReport: async (inspectionId, sectionKey, sectionData) => {
    const inspection = await getLocalInspection(inspectionId)
    if (!inspection) return

    const reportData = inspection.report_data
      ? JSON.parse(inspection.report_data)
      : {}

    reportData[sectionKey] = sectionData
    await get().setReportData(inspectionId, reportData)
  },

  updateItemInReport: async (inspectionId, sectionKey, itemKey, itemData) => {
    const inspection = await getLocalInspection(inspectionId)
    if (!inspection) return

    const reportData = inspection.report_data
      ? JSON.parse(inspection.report_data)
      : {}

    if (!reportData[sectionKey]) reportData[sectionKey] = {}
    if (!reportData[sectionKey].items) reportData[sectionKey].items = {}
    reportData[sectionKey].items[itemKey] = {
      ...(reportData[sectionKey]?.items?.[itemKey] || {}),
      ...itemData,
    }

    await get().setReportData(inspectionId, reportData)
  },
}))
