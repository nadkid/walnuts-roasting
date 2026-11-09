export const mainPages=['today','stock','green','batches','orders','profit','plan','settings'];
export const settingsTabs={coffees:'Coffees',products:'Products & POS',mappings:'Mappings',planning:'Planning',connections:'Connections',exceptions:'Exceptions',access:'Access',data:'Data'};

export function routeForHash(hash,currentTab='coffees'){
  const [page,detail]=hash.replace(/^#/,'').split('/');
  if(page==='products')return {view:'settings',tab:'products',hash:'#settings/products'};
  const view=mainPages.includes(page)?page:'today';
  const tab=view==='settings'&&Object.hasOwn(settingsTabs,detail)?detail:currentTab;
  return {view,tab,detail};
}
