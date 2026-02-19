import { PropType } from 'vue';
import { Calendar, CalendarOptions } from '@fullcalendar/core';
import { CustomRendering } from '@fullcalendar/core/internal';
declare const FullCalendar: import("vue").DefineComponent<import("vue").ExtractPropTypes<{
    options: PropType<CalendarOptions>;
}>, {}, {
    renderId: number;
    customRenderingMap: Map<string, CustomRendering<any>>;
}, {}, {
    getApi(): Calendar;
    buildOptions(suppliedOptions: CalendarOptions | undefined): CalendarOptions;
}, import("vue").ComponentOptionsMixin, import("vue").ComponentOptionsMixin, {}, string, import("vue").PublicProps, Readonly<import("vue").ExtractPropTypes<{
    options: PropType<CalendarOptions>;
}>> & Readonly<{}>, {}, {}, {}, {}, string, import("vue").ComponentProvideOptions, true, {}, any>;
export default FullCalendar;
