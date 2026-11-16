/** @typedef {{id:number,code:string,route:string,zone:string,driver:string,archive_task_id:number|null}} Shipment */
/** @typedef {{id:number,state:'queued'|'running'|'done'|'failed',result:object}} Study */
/** @typedef {{id:number,kind:'archiving'|'restoring',state:'queued'|'running'|'done'|'failed',stage:string,shipment_ids:number[],package_path:string,checksum:string,progress:object,error:string,compare:object}} ArchiveTask */
/** @typedef {{origin_shipment_id:number,task_id:number,code:string,route:string,zone:string,driver:string,samples:number}} ArchivedShipment */
