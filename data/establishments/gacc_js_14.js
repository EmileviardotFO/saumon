/**
 * 初始化autocompleter组件
 * options说明：
 * tableName 标准代码类型
 * keyValue  标准代码值，可选
 * hiddenId 隐藏框id
 * dorpUp 是否向上展现下拉框，可选
 */


(function($) {
	$.fn
			.extend({
				"autocomp" : function(options) {
					var input = $(this);
					var paraName= options.tableName;
					// var basePath = baseUrl;
					var keyValue=options.keyValue;
					var hid=options.hiddenId;
					var callbackfn=options.callback;
					var orderColumn=options.orderColumn;
					var orderRule=options.orderRule;
					var filterCon=options.filterCon;
					var limit=options.limit;
					var tipsData=options.tipsData;
					var spchar=options.spchar;
					var readflag=options.readflag;
					
					// 如果存在初始化keyValue
					if(typeof(options.keyValue)!=="undefined"){
						var jsonObj = {};
						jsonObj.paraName =paraName;
						jsonObj.keyValue =keyValue;
						jsonObj.orderRule =orderRule;
						jsonObj.orderColumn =orderColumn;
						jsonObj.filterCon=filterCon;
						jsonObj.readflag=readflag;
						//最大一次取5000条数据
						jsonObj.rowNum=5000;
						$.ajax({
							url : ciferEnum.querypara["公共参数初始化值查询"],
							data : jsonObj,
							dataType : "json",
							type : "get",
							contentType : "application/json;charset=utf-8",
							success : function(data) {
								input.val(data.codeName);
								$("#"+hid).val(data.codeValue);
							}
						});

					}

					//新增向上展示列表功能 peiyang
		            if(typeof(options.dropUp)=="undefined"){
		            	options.dropUp = false;
		            }

					var jsonObj1 = {};
					jsonObj1.paraName =paraName;
					jsonObj1.orderRule =orderRule;
					jsonObj1.orderColumn =orderColumn;
					jsonObj1.filterCon=filterCon;
					jsonObj1.readflag=readflag;
					//最大一次取5000条数据
					jsonObj1.rowNum=5000;
					$.ajax({
								url : ciferEnum.querypara["公共参数下拉框列表查询"],
								data : jsonObj1,
								dataType : "json",
								type : "get",
								contentType : "application/json;charset=utf-8",
								success : function(data) {
									// 根据返回参数构造json
									var compJson = [];
									var customsArry=['4205','4206','4207','4212','4216','4226','4229',
									                 '4233','4234','4235','4237','4239','4244','4248',
									                 '4249','4251','4255'];//作废关区
									if(paraName=='CUS_CUSTOMS'){//过滤废弃关区
										for (var i = 0; i < data.length; i++) {
											if(customsArry.indexOf(data[i].codeValue)==-1){
												compJson[i] = {
														value : data[i].codeValue,
														name : data[i].codeName,
			                                            label : data[i].codeValue + "-" + data[i].codeName//data[i].codeValue + "-" + data[i].codeName
													}
											}
										}
									}else{
										for (var i = 0; i < data.length; i++) {
											compJson[i] = {
													value : data[i].codeValue,
													name : data[i].codeName,
		                                            label : data[i].codeValue + "-" + data[i].codeName//data[i].codeValue + "-" + data[i].codeName
												}
										}
									}
									input.autocompleter({
												source : compJson,
												hiddenId : options.hiddenId,
												style:options.style,
												limit:limit,
												dropUp: options.dropUp,
												saveFlag:options.saveFlag,//added for 水运舱单支持保存功能 by chenyongda 20190115
												tipsData:tipsData,//增加tips提示
												spchar:spchar,//自定义分隔符
												callback : function(lable,index,obj) {
													//执行回调函数
													if(callbackfn&&typeof callbackfn =='function'){
														callbackfn(obj.value,obj);
//														eval(callbackfn+"('"+obj.value+"')");
													}

												}
											});
								},
								error : function(xhr) {
									console.log(xhr);
								}
							});

				},
		        "autocomp1" : function(options) {
					var input = $(this);
					var paraName= options.tableName;
					// var basePath = baseUrl;
					var keyValue=options.keyValue;
					var hid=options.hiddenId;
					var callbackfn=options.callback;
					var orderColumn=options.orderColumn;
					var orderRule=options.orderRule;
					var filterCon=options.filterCon;
                    var tipsData = options.tipsData;
                    var limit=options.limit;
                    var url = options.url;
					// 如果存在初始化keyValue
					if(typeof(options.keyValue)!=="undefined"){
						var jsonObj = {};
						jsonObj.paraName =paraName;
						jsonObj.keyValue =keyValue;
						jsonObj.orderRule =orderRule;
						jsonObj.orderColumn =orderColumn;
						jsonObj.filterCon=filterCon;
						//最大一次取5000条数据
						jsonObj.rowNum=5000;
						$.ajax({
							url : url,
							data : jsonObj,
							dataType : "json",
							type : "get",
							contentType : "application/json;charset=utf-8",
							success : function(data) {
								input.val(data.codeName);
								$("#"+hid).val(data.codeValue);
								
							}
						});

					}

					//新增向上展示列表功能 peiyang
		            if(typeof(options.dropUp)=="undefined"){
		            	options.dropUp = false;
		            }

					var jsonObj1 = {};
					jsonObj1.paraName =paraName;
					jsonObj1.orderRule =orderRule;
					jsonObj1.orderColumn =orderColumn;
					jsonObj1.filterCon=filterCon;
					//最大一次取5000条数据
					jsonObj1.rowNum=5000;
					$.ajax({
								url : url,
								//data : jsonObj1,
								dataType : "json",
								type : "get",
								contentType : "application/json;charset=utf-8",
								success : function(data) {
									// 根据返回参数构造json
									var compJson = [];
									for (var i = 0; i < data.length; i++) {
										compJson[i] = {
											value : data[i].codeValue,
											name : data[i].codeName,
                                            label : data[i].codeValue + "-" + data[i].codeName//data[i].codeValue + "-" + data[i].codeName
										}
										//所有数据
										compJson[i].allData =data[i];
									}
									input.autocompleter({
												source : compJson,
												hiddenId : options.hiddenId,
												style:options.style,
												limit:limit,
												dropUp: options.dropUp,
                                                tipsData:tipsData,
												callback : function(lable,index,obj) {
													//执行回调函数
													if(callbackfn&&typeof callbackfn =='function'){
														callbackfn(obj.value,obj);
//														eval(callbackfn+"('"+obj.value+"')");
													}

												}
											});
								},
								error : function(xhr) {
									console.log(xhr);
								}
							});

				},
		        "autocomplocal": function(options) {
					var input = $(this);
					var paraName= options.tableName;
					var keyValue=options.keyValue;
					var hid=options.hiddenId;
					var callbackfn=options.callback;
					var orderColumn=options.orderColumn;
					var orderRule=options.orderRule;
		            var filterCon=options.filterCon;
		            var limit=options.limit;
		            var tipsData=options.tipsData;
		            var spchar=options.spchar;
		            var readflag=options.readflag;
		            
		            var jsonObj = {};
		            jsonObj.paraName =paraName;
					jsonObj.keyValue =keyValue;
					jsonObj.orderRule =orderRule;
					jsonObj.orderColumn =orderColumn;
					jsonObj.filterCon=filterCon;
					jsonObj.readflag=readflag;
					//最大一次取5000条数据
					jsonObj.rowNum=5000;
					//URL为loaclstorge每个参数的key
					var URL = ciferEnum.querypara["公共参数下拉框列表查询"]+'?paraName='+paraName+'&rowNum=5000';
		         // 如果存在初始化keyValue
					if(typeof(options.keyValue)!=="undefined"){
						$.ajax({
							url : ciferEnum.querypara["公共参数初始化值查询"],
							data : jsonObj,
							dataType : "json",
							type : "get",
							contentType : "application/json;charset=utf-8",
							success : function(data) {
								input.val(data.codeName);
								$("#"+hid).val(data.codeValue);
							}
						});
					}
		            
					//新增向上展示列表功能 peiyang
		            if(typeof(options.dropUp)=="undefined"){
		            	options.dropUp = false;
		            }
		            
		        	if(supportLocalStorage){//如果浏览器支持LocalStorage
		        		
		        		var source =_getCache(URL);
		        		if(source){//已经存在本url的缓存
		        			input.autocompleter({
		                        source: source,
		                        hiddenId: options.hiddenId,
		                        style:options.style,
		                        dropUp: options.dropUp,
		                        saveFlag:options.saveFlag,//added for 水运舱单支持保存功能 by chenyongda 20190115
		                        tipsData:tipsData,//增加tips提示
		                        spchar:spchar,//自定义分隔符
		                        callback: function(lable, index, obj) {
		                            //执行回调函数
		                            if (callbackfn && typeof callbackfn == 'function') {
		                                callbackfn(obj.value,obj);
		                            }
	
		                        }
		                    });
		        		}else{
		        			//不存在本url的缓存，从数据库获取
							var jsonObj1 = {};
							jsonObj1.paraName =paraName;
							jsonObj1.orderRule =orderRule;
							jsonObj1.orderColumn =orderColumn;
							jsonObj1.filterCon=filterCon;
							//最大一次取5000条数据
							jsonObj1.rowNum=5000;
		        			
		        			
				            $.ajax({
				                url: ciferEnum.querypara["公共参数下拉框列表查询"],
				                data: jsonObj1,
				                dataType: "json",
				                type: "get",
				                contentType: "application/json;charset=utf-8",
				                success: function(data) {
				                    // 根据返回参数构造json
				                    var compJson = [];
				                    for (var i = 0; i < data.length; i++) {
				                    	//自定义分隔符
				                    	if(spchar){
				                    		compJson[i] = {
						                            value: data[i].codeValue,
						                            label: data[i].codeValue + spchar + data[i].codeName
						                        }
				                    	}else{
				                    		compJson[i] = {
						                            value: data[i].codeValue,
						                            label: data[i].codeValue + "-" + data[i].codeName
						                        }
				                    	}
 
				                    }
				                    input.autocompleter({
				                        source: compJson,
				                        hiddenId: options.hiddenId,
				                        dropUp: options.dropUp,
				                        style:options.style,
				                        limit:limit,
				                        dropUp: options.dropUp,
				                        saveFlag:options.saveFlag,//added for 水运舱单支持保存功能 by chenyongda 20190115
				                        tipsData:tipsData,//增加tips提示
				                        spchar:spchar,//自定义分隔符
				                        callback: function(lable, index, obj) {
				                            //执行回调函数
				                            if (callbackfn && typeof callbackfn == 'function') {
				                                callbackfn(obj.value,obj);
				                            }
			
				                        }
				                    });
				                    //将数据写入loaclstorge缓存
				                    _setCache(URL, compJson);
				                    
				                },
				                error: function(xhr) {
				                    console.log(xhr);
				                }
				            });
		        			
		        		}
		        		
		        	}
		        },
		 //支持四列 张正、郝永强       
		     "gblocal": function(options) {
					var input = $(this);
					var paraName= options.tableName;
					var keyValue=options.keyValue;
					var hid=options.hiddenId;
					var callbackfn=options.callback;
					var orderColumn=options.orderColumn;
					var orderRule=options.orderRule;
		            var filterCon=options.filterCon;
		            var limit=options.limit;		            
		            //是否走缓存
		            var notStorage=options.notStorage;
		            var readflag=options.readflag;
		            var jsonObj = {};
		            jsonObj.paraName =paraName;
					jsonObj.keyValue =keyValue;
					jsonObj.orderRule =orderRule;
					jsonObj.orderColumn =orderColumn;
					jsonObj.filterCon=filterCon;
					//最大一次取5000条数据
					jsonObj.rowNum=5000;
					//URL为loaclstorge每个参数的key
					var URL =ciferEnum.querypara["公共参数下拉框列表查询"]+'?paraName='+paraName+'&rowNum=5000';
					
		         // 如果存在初始化keyValue
					if(typeof(options.keyValue)!=="undefined"){
						$.ajax({
							url : ciferEnum.querypara["公共参数初始化值查询"],
							data : jsonObj,
							dataType : "json",
							type : "get",
							contentType : "application/json;charset=utf-8",
							success : function(data) {
								input.val(data.cusCode+"-"+data.codeName);
								$("#"+hid).val(data.codeValue);
							}
						});
					}
		            
					//新增向上展示列表功能 peiyang
		            if(typeof(options.dropUp)=="undefined"){
		            	options.dropUp = false;
		            }
		            
		        	if(supportLocalStorage){//如果浏览器支持LocalStorage
		        		
		        		var source =_getCache(URL);
		        		if(source&&!notStorage){//已经存在本url的缓存
		        			input.autocompleter({
		                        source: source,
		                        hiddenId: options.hiddenId,
		                        style:options.style,
		                        template:options.template,
		                        dropUp: options.dropUp,
		                        limit:limit,
		                        callback: function(lable, index, obj) {
									if(index>=0){
										input.val(obj.cusCode+"-"+obj.codeName);
								   		$("#"+hid).val(obj.codeValue);
									}
		                            //执行回调函数
		                            if (callbackfn && typeof callbackfn == 'function') {
		                                callbackfn(obj.value,obj);
		                            }
	
		                        }
		                    });
		        		}else{
		        			//不存在本url的缓存，从数据库获取
							var jsonObj1 = {};
							jsonObj1.paraName =paraName;
							jsonObj1.orderRule =orderRule;
							jsonObj1.orderColumn =orderColumn;
							jsonObj1.filterCon=filterCon;
							jsonObj1.readflag=readflag;
							//最大一次取5000条数据
							jsonObj1.rowNum=5000;
		        			
		        			
				            $.ajax({
				                url: ciferEnum.querypara["参数查询gbParaList"],
				                data: jsonObj1,
				                dataType: "json",
				                type: "get",
				                contentType: "application/json;charset=utf-8",
				                success: function(data) {
				                    // 根据返回参数构造json
				                    var compJson = [];
				                    for (var i = 0; i < data.length; i++) {
				                        compJson[i] = {
				                        	codeValue: data[i].codeValue,
				                        	codeName:data[i].codeName,
				                        	cusCode:data[i].cusCode,
				                        	ciqCode:data[i].ciqCode,
								gbName:data[i].gbName,
				                            label: data[i].cusCode + "_" + data[i].codeName+ "_" + data[i].codeValue+ "_" + data[i].ciqCode 
				                        }
				                    }
				                    input.autocompleter({
				                        source: compJson,
				                        hiddenId: options.hiddenId,
				                        style:options.style,
				                        template:options.template,
				                        dropUp: options.dropUp,
				                        limit:limit,
				                        callback: function(lable, index, obj) {
				                        	if(index>=0){
												input.val(obj.cusCode+"-"+obj.codeName);
												$("#"+hid).val(obj.codeValue);
				                        	}
				                            //执行回调函数
				                            if (callbackfn && typeof callbackfn == 'function') {
				                                callbackfn(obj.cusCode,obj);
				                            }
			
				                        }
				                    });
				                    //将数据写入loaclstorge缓存
				                    _setCache(URL, compJson);
				                    
				                },
				                error: function(xhr) {
				                    console.log(xhr);
				                }
				            });
		        			
		        		}
		        		
		        	}
				},
		        "autocompremove" : function(options) {//仅供食品司注册海关下拉框使用（默认去除总署）
					var input = $(this);
					var paraName= options.tableName;
					// var basePath = baseUrl;
					var keyValue=options.keyValue;
					var hid=options.hiddenId;
					var callbackfn=options.callback;
					var orderColumn=options.orderColumn;
					var orderRule=options.orderRule;
					var filterCon=options.filterCon;
					var limit=options.limit;
					// 如果存在初始化keyValue
					if(typeof(options.keyValue)!=="undefined"){
						var jsonObj = {};
						jsonObj.paraName =paraName;
						jsonObj.keyValue =keyValue;
						jsonObj.orderRule =orderRule;
						jsonObj.orderColumn =orderColumn;
						jsonObj.filterCon=filterCon;
						//最大一次取5000条数据
						jsonObj.rowNum=5000;
						$.ajax({
							url : ciferEnum.querypara["公共参数初始化值查询"],
							data : jsonObj,
							dataType : "json",
							type : "get",
							contentType : "application/json;charset=utf-8",
							success : function(data) {
								input.val(data.codeName);
								$("#"+hid).val(data.codeValue);
							}
						});

					}

					//新增向上展示列表功能 peiyang
		            if(typeof(options.dropUp)=="undefined"){
		            	options.dropUp = false;
		            }

					var jsonObj1 = {};
					jsonObj1.paraName =paraName;
					jsonObj1.orderRule =orderRule;
					jsonObj1.orderColumn =orderColumn;
					jsonObj1.filterCon=filterCon;
					var filterConNum= filterCon.replace(/[^0-9]/ig,"");
					//最大一次取5000条数据
					jsonObj1.rowNum=5000;
					$.ajax({
								url : ciferEnum.querypara["公共参数下拉框列表查询"],
								data : jsonObj1,
								dataType : "json",
								type : "get",
								contentType : "application/json;charset=utf-8",
								success : function(data) {
									// 根据返回参数构造json
									var compJson = [];
									var customsArry=['4205','4206','4207','4212','4216','4226','4229',
									                 '4233','4234','4235','4237','4239','4244','4248',
									                 '4249','4251','4255'];//作废关区
									for (var i = 0; i < data.length; i++) {
//										if(data[i].codeValue != filterCon.substring(filterCon.length-3,filterCon.length-1) + "00"){
										if(data[i].codeValue != filterConNum + "00"&&customsArry.indexOf(data[i].codeValue)==-1){
											compJson[i] = {
													value : data[i].codeValue,
													name : data[i].codeName,
		                                            label : data[i].codeValue + "-" + data[i].codeName//data[i].codeValue + "-" + data[i].codeName
												}
										}
									}
									input.autocompleter({
												source : compJson,
												hiddenId : options.hiddenId,
												style:options.style,
												limit:limit,
												dropUp: options.dropUp,
												callback : function(lable,index,obj) {
													//执行回调函数
													if(callbackfn&&typeof callbackfn =='function'){
														callbackfn(obj.value,obj);
//														eval(callbackfn+"('"+obj.value+"')");
													}

												}
											});
								},
								error : function(xhr) {
									console.log(xhr);
								}
							});
		        }
			});
})(jQuery);

//loaclstorge的键
var localStorageKey ='autocompleterKey';
var cache=_loadCache();

/**
 * 判断浏览器是否支持localstorge
 * @returns {Boolean}
 */
function supportLocalStorage() {
	var supported = typeof window.localStorage !== 'undefined';
	if (supported) {
	    try {
	        localStorage.setItem("autocompleter", "autocompleter");
	        localStorage.removeItem("autocompleter");
	    } catch (e) {
	        supported = false;
	    }
	}
	return supported;
}

/**
 * 存储localstorge
 * @param url
 * @param data
 */
function _setCache(url, data) {
    if (!supportLocalStorage) { return; }
    if (url && data) {
        cache[url] = {
            value: data
        };

        // Proccess to localStorage
        try {
              localStorage.setItem(localStorageKey, JSON.stringify(cache));
        } catch (e) {
              var code = e.code || e.number || e.message;
              if (code === 22) {
                _deleteCache();
              } else {
                throw(e);
              }
        }
    }
}

/**
 * 读取localstorge
 * @param url
 * @returns
 */
function _loadCache() {
    if (!supportLocalStorage) { return; }
    var json = localStorage.getItem(localStorageKey) || '{}';
    return JSON.parse(json);
}
/**
 * 获取缓存数据
 * @param url
 * @returns
 */
function _getCache(url) {
    if (!url) { return; }
    var response = (cache[url] && cache[url].value) ? cache[url].value : false;
    return response;
}
/**
 * 删除localstorge
 */
function _deleteCache() {
    try {
        localStorage.removeItem(localStorageKey);
        cache = _loadCache();
    } catch (e) {
        throw(e);
    }
}