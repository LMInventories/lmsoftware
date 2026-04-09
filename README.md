# InspectPro

A cloud property inventory inspection platform for letting agencies and inventory clerks.

---

## Overview

InspectPro is a full-stack property inventory system built for professional inventory clerks and the agencies that manage them. Clerks carry out inspections on a mobile device; managers review, approve, and distribute reports from a web dashboard.

The platform handles the full inspection lifecycle — from scheduling and template setup through to PDF report generation and client delivery.

---

## Web Application

The web app is used by agency managers, administrators, and client companies. It is the central control point for everything outside of the physical inspection itself.

### Clients & Properties

Agencies manage a list of clients (landlords or letting companies), each with their own branding — logo, colour scheme, and report disclaimer. Properties are linked to clients and carry address details and overview photos. Each client's report style is configured once and applied automatically to every inspection.

### Inspection Management

Inspections are created against a property and assigned to a clerk. They move through a defined workflow: Draft → In Progress → Review → Complete. Managers can see the status of every open inspection at a glance from the dashboard and step in at the Review stage to check the report before it is finalised.

### Templates

Inspection templates define the structure of a report — which fixed sections to include (condition summary, cleaning notes, keys, meter readings, smoke alarms, and so on) and which room types and items to expect. Templates are fully configurable; items can have descriptions, conditions, and photos attached to them.

### Edit Report

The Edit Report page gives managers a full in-browser view of a clerk's submitted report. Every field is editable. Items can be reordered, added, or removed. Photos can be uploaded or deleted. Sub-items — where a single room item contains multiple components each with their own condition — can be managed directly.

### Review & Export

At the Review stage, managers can open a live branded preview of the report before approving it. Once marked Complete, the report can be exported as a formatted PDF and emailed directly to the client from within the platform. The PDF reflects the client's branding including logo, header colour, and custom disclaimer text.

### Settings & Branding

Each client account has a dedicated settings page where report colours, header text colour, logo, orientation (portrait or landscape), and photo layout preferences are configured. Changes take effect immediately in both the preview and exported PDF.

### Users

The platform supports multiple user roles. Administrators manage clients, properties, templates, and users. Managers oversee inspections and handle report approval. Clerks are assigned inspections and use the mobile app to carry them out.

---

## Mobile App

The mobile app is used by clerks on-site during inspections. It is built for offline-first use — all data is stored locally and synced to the server when a connection is available.

### Inspections

Clerks log in and fetch their assigned inspections. Each inspection is presented room by room, following the structure defined by the template. For each item in a room, the clerk can fill in a description and condition, add photos, and attach sub-items where a component has multiple distinct elements.

### Photography

Photos can be captured in-app or selected from the device gallery. The camera interface is aware of the current room and item, so photos are automatically attached to the right place in the report. Multiple photos per item are supported, and a photo grid view lets clerks review and delete images before syncing.

### AI Dictation

Rather than typing, clerks can dictate their observations using the built-in AI transcription system. The clerk records one or more audio clips while walking through a room, speaking each item name followed by a description and condition. When they tap Transcribe, all clips are sent to the backend where they are transcribed by Whisper and then interpreted by Claude, which maps the spoken content to the correct items and fills the report fields automatically.

The system understands natural spoken descriptions, condition phrases, quantities, and British English terminology. It handles multi-component items — where a clerk describes several elements each with their own condition — using a simple spoken trigger to separate them. Clerks can also dictate corrections to individual fields without re-recording the whole room.

The help guide inside the app explains how to structure dictation for best results, with examples.

### Sync

Once an inspection is complete on-device, the clerk syncs it to the server. The sync uploads all report data and photos in a single operation. Progress is shown during the upload. After a successful sync the inspection moves to the Review stage for a manager to check.

### Check-Out Mode

For check-out inspections, the app can display the original check-in report alongside the current fields, allowing the clerk to compare conditions item by item as they work through the property.

---

## Hosting

All services — backend API, web application, and database — are hosted on Railway. The mobile app is distributed as an Android APK built via GitHub Actions.
